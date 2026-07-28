# Copyright (c) 2025 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""PDF chunk planning, OCR execution, and result merging."""

import concurrent.futures
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from cache_store import (
    _hash_file,
    build_cache_namespace,
    build_chunk_cache_key,
    cache_entry_lock,
    load_cached_result,
    save_cached_result,
)
from config import (
    FILE_TYPE_PDF,
    MAX_LOCAL_FILE_BYTES,
    get_max_chunk_workers,
    get_max_pages_per_request,
    get_task_timeout_seconds,
    resolve_access_token,
    resolve_api_url,
    metric_add,
)
from contracts import ParseResult
from ocr_client import parse_document
from split_pdf import get_pdf_page_count, split_pdf

DEFAULT_MAX_TOTAL_PAGES = 5000
MERGE_SCHEMA_VERSION = 2


def merge_metrics(
    target: Optional[dict[str, float]],
    source: Optional[dict[str, float]],
) -> None:
    if target is None or source is None:
        return
    for key, value in source.items():
        target[key] = target.get(key, 0.0) + value


def build_pdf_chunks(
    total_pages: int,
    chunk_size: int,
) -> list[tuple[int, int]]:
    return [
        (start, min(start + chunk_size - 1, total_pages))
        for start in range(1, total_pages + 1, chunk_size)
    ]


def merge_chunk_results(
    chunk_results: list[dict],
    chunk_ranges: Optional[list[tuple[int, int]]] = None,
) -> dict:
    if not chunk_results:
        raise ValueError("No chunk results to merge")
    if chunk_ranges is not None and len(chunk_ranges) != len(chunk_results):
        raise ValueError("Chunk result count does not match planned ranges")

    merged_texts: list[str] = []
    merged_pages: list[dict] = []
    merged_chunks: list[dict] = []
    merged_assets: dict[str, str] = {}
    expected_total = 0
    last_end = 0

    for index, chunk_result in enumerate(chunk_results, start=1):
        if not chunk_result.get("ok"):
            return chunk_result
        coverage = chunk_result.get("coverage")
        raw_result = chunk_result.get("result")
        provider_pages = []
        if isinstance(raw_result, dict):
            nested_result = raw_result.get("result")
            if isinstance(nested_result, dict):
                provider_pages = nested_result.get("layoutParsingResults") or []
        if not isinstance(provider_pages, list):
            raise ValueError("Chunk result page list is invalid")
        if not isinstance(coverage, dict):
            coverage = {
                "expected_pages": len(provider_pages),
                "returned_pages": len(provider_pages),
                "missing_pages": [],
                "empty_pages": [],
                "duplicate_pages": [],
                "page_ids": [],
                "partial": False,
                "complete": True,
            }
        if coverage.get("complete") is not True:
            raise ValueError(f"Chunk {index} is not complete")
        if (
            coverage.get("partial") is not False
            or coverage.get("missing_pages") != []
            or coverage.get("duplicate_pages") != []
        ):
            raise ValueError(f"Chunk {index} has incomplete page coverage")
        expected_coverage_pages = coverage.get("expected_pages")
        returned_pages = coverage.get("returned_pages")
        if (
            not isinstance(expected_coverage_pages, int)
            or expected_coverage_pages < 1
            or not isinstance(returned_pages, int)
            or returned_pages < 1
            or expected_coverage_pages != returned_pages
        ):
            raise ValueError(f"Chunk {index} has invalid page coverage")
        if raw_result is not None and len(provider_pages) != returned_pages:
            raise ValueError(
                f"Chunk {index} raw page count ({len(provider_pages)}) does not "
                f"match coverage ({returned_pages})"
            )
        if not provider_pages and raw_result is None:
            provider_pages = [None] * returned_pages

        if chunk_ranges is not None:
            start_page, end_page = chunk_ranges[index - 1]
            expected_pages = end_page - start_page + 1
            if coverage.get("returned_pages") != expected_pages:
                raise ValueError(
                    f"Chunk {index} returned {coverage.get('returned_pages')} "
                    f"page(s), expected {expected_pages}"
                )
            if start_page != last_end + 1:
                raise ValueError("Chunk page ranges are not contiguous")
            last_end = end_page
            expected_total = end_page
        else:
            start_page = None
            end_page = None
            expected_total += returned_pages

        text = chunk_result.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Chunk {index} has empty Markdown text")
        merged_texts.append(text)
        assets = chunk_result.get("assets")
        if isinstance(assets, dict):
            merged_assets.update(
                {str(key): str(value) for key, value in assets.items()}
            )

        merged_chunks.append(
            {
                "chunk_index": index,
                "source_page_start": start_page,
                "source_page_end": end_page,
                "coverage": coverage,
                "provider_response": raw_result,
            }
        )
        for local_index, page in enumerate(provider_pages):
            source_page = (
                start_page + local_index
                if start_page is not None
                else None
            )
            merged_pages.append(
                {
                    "source_page": source_page,
                    "provider_page": page,
                }
            )

    merged_coverage = {
        "expected_pages": expected_total,
        "returned_pages": len(merged_pages),
        "missing_pages": [],
        "empty_pages": [],
        "duplicate_pages": [],
        "page_ids": list(range(1, len(merged_pages) + 1)),
        "partial": False,
        "complete": len(merged_pages) == expected_total,
    }
    if not merged_coverage["complete"]:
        raise ValueError("Merged chunks do not cover the complete source document")
    return {
        "ok": True,
        "text": "\n\n".join(merged_texts),
        "result": {
            "schema_version": MERGE_SCHEMA_VERSION,
            "type": "chunked_ocr",
            "chunks": merged_chunks,
            "merged": {
                "pages": merged_pages,
                "text": "\n\n".join(merged_texts),
            },
        },
        "coverage": merged_coverage,
        "assets": merged_assets,
        "error": None,
    }


def append_chunk_retry_hint(error_message: str, use_cache: bool) -> str:
    if use_cache:
        cache_hint = (
            "Rerun the same command with cache enabled and the same --chunk-pages "
            "to reuse successful chunks and retry only missing ranges."
        )
    else:
        cache_hint = (
            "This run used --no-cache, so successful chunks were not reusable. "
            "Rerun without --no-cache and keep the same --chunk-pages for "
            "resumable retries."
        )
    return f"{error_message} {cache_hint}".strip()


def parse_with_auto_split(
    file_path: str,
    file_type: Optional[int],
    cache_dir: Optional[Path] = None,
    use_cache: bool = True,
    api_url: Optional[str] = None,
    token: Optional[str] = None,
    metrics: Optional[dict[str, float]] = None,
    chunk_pages: Optional[int] = None,
    chunk_workers: Optional[int] = None,
    deadline: Optional[float] = None,
    cancel_event: Optional[threading.Event] = None,
    allow_insecure_http: bool = False,
    **options,
) -> ParseResult:
    resolved_file_type = file_type
    if resolved_file_type is None and file_path.lower().endswith(".pdf"):
        resolved_file_type = FILE_TYPE_PDF
    if resolved_file_type != FILE_TYPE_PDF:
        return parse_document(
            file_path=file_path,
            file_type=file_type,
            api_url=api_url,
            token=token,
            deadline=deadline,
            cancel_event=cancel_event,
            allow_insecure_http=allow_insecure_http,
            **options,
        )

    raw_input_path = Path(file_path).expanduser()
    if raw_input_path.is_symlink() and os.getenv(
        "PADDLEOCR_ALLOW_SYMLINKS",
        "",
    ).lower() not in {"1", "true", "yes"}:
        return {
            "ok": False,
            "text": "",
            "result": None,
            "error": {
                "code": "INPUT_ERROR",
                "message": "symbolic-link inputs are disabled by default",
            },
        }
    if not raw_input_path.is_file():
        return {
            "ok": False,
            "text": "",
            "result": None,
            "error": {
                "code": "INPUT_ERROR",
                "message": f"Not a file: {raw_input_path}",
            },
        }
    try:
        source_stat = raw_input_path.stat()
        if source_stat.st_size <= 0:
            raise ValueError(f"File is empty: {raw_input_path}")
        if source_stat.st_size > MAX_LOCAL_FILE_BYTES:
            raise ValueError(
                "Local source file exceeds the hard limit of "
                f"{MAX_LOCAL_FILE_BYTES // 1024 // 1024} MB"
            )
        with raw_input_path.open("rb") as source:
            if not source.read(5).startswith(b"%PDF-"):
                raise ValueError("Input does not contain a valid PDF signature")
    except (OSError, ValueError) as exc:
        return {
            "ok": False,
            "text": "",
            "result": None,
            "error": {"code": "INPUT_ERROR", "message": str(exc)},
        }

    input_path = raw_input_path.resolve()
    if deadline is None:
        deadline = time.monotonic() + get_task_timeout_seconds()
    try:
        api_url, _ = resolve_api_url(
            api_url,
            allow_insecure_http=allow_insecure_http,
        )
        token, _ = resolve_access_token(token)
    except ValueError as exc:
        return {
            "ok": False,
            "text": "",
            "result": None,
            "error": {"code": "CONFIG_ERROR", "message": str(exc)},
        }

    page_count_started_at = time.perf_counter()
    try:
        total_pages = get_pdf_page_count(input_path)
        if total_pages <= 0 or total_pages > DEFAULT_MAX_TOTAL_PAGES:
            raise ValueError(
                f"PDF page count must be between 1 and {DEFAULT_MAX_TOTAL_PAGES}"
            )
    except Exception as exc:
        return {
            "ok": False,
            "text": "",
            "result": None,
            "error": {
                "code": "INPUT_ERROR",
                "message": f"{type(exc).__name__}: {str(exc)[:500]}",
            },
        }
    finally:
        metric_add(
            metrics,
            "page_count_seconds",
            time.perf_counter() - page_count_started_at,
        )

    try:
        max_pages_per_request = get_max_pages_per_request(chunk_pages)
        max_chunk_workers = get_max_chunk_workers(chunk_workers)
    except ValueError as exc:
        return {
            "ok": False,
            "text": "",
            "result": None,
            "error": {"code": "INPUT_ERROR", "message": str(exc)},
        }
    if total_pages <= max_pages_per_request:
        return parse_document(
            file_path=str(input_path),
            file_type=file_type,
            api_url=api_url,
            token=token,
            metrics=metrics,
            expected_pages=total_pages,
            deadline=deadline,
            cancel_event=cancel_event,
            allow_insecure_http=allow_insecure_http,
            **options,
        )

    chunk_ranges = build_pdf_chunks(total_pages, max_pages_per_request)
    print(
        (
            f"Large PDF detected ({total_pages} pages). "
            f"Splitting into {len(chunk_ranges)} chunk(s) of up to "
            f"{max_pages_per_request} pages."
        ),
        file=sys.stderr,
    )
    effective_workers = min(max_chunk_workers, len(chunk_ranges))

    try:
        source_size = input_path.stat().st_size
        free_bytes = shutil.disk_usage(tempfile.gettempdir()).free
        per_worker_bytes = min(
            max(source_size * 2, 64 * 1024 * 1024),
            512 * 1024 * 1024,
        )
        estimated_bytes = per_worker_bytes * effective_workers
        if free_bytes < estimated_bytes:
            raise OSError(
                "insufficient temporary disk space; need about "
                f"{estimated_bytes // 1024 // 1024} MB"
            )
    except OSError as exc:
        return {
            "ok": False,
            "text": "",
            "result": None,
            "error": {"code": "INPUT_ERROR", "message": str(exc)},
        }

    with tempfile.TemporaryDirectory(prefix="paddleocr_split_") as temp_dir:
        temp_dir_path = Path(temp_dir)
        chunk_jobs: list[tuple[int, int, int, Optional[str]]] = []
        chunk_results_by_index = {}
        cache_namespace = build_cache_namespace(api_url, token)
        try:
            source_digest = _hash_file(input_path)
        except OSError as exc:
            return {
                "ok": False,
                "text": "",
                "result": None,
                "error": {"code": "INPUT_ERROR", "message": str(exc)},
            }

        for chunk_index, (start_page, end_page) in enumerate(
            chunk_ranges,
            start=1,
        ):
            chunk_cache_key = None
            if use_cache and cache_dir is not None:
                chunk_cache_key = build_chunk_cache_key(
                    input_path,
                    start_page,
                    end_page,
                    FILE_TYPE_PDF,
                    options,
                    cache_namespace,
                    content_digest=source_digest,
                )
            chunk_jobs.append(
                (chunk_index, start_page, end_page, chunk_cache_key)
            )

        run_cancel = cancel_event or threading.Event()

        def parse_chunk_job(
            chunk_index: int,
            start_page: int,
            end_page: int,
            chunk_cache_key: Optional[str],
        ) -> tuple[int, dict, dict[str, float]]:
            chunk_metrics = {"chunk_parse_count": 1.0}
            print(
                (
                    f"Parsing chunk {chunk_index}/{len(chunk_ranges)} "
                    f"pages {start_page}-{end_page}"
                ),
                file=sys.stderr,
            )
            if run_cancel.is_set():
                return (
                    chunk_index,
                    {
                        "ok": False,
                        "text": "",
                        "result": None,
                        "error": {
                            "code": "CANCELLED",
                            "message": "chunk cancelled",
                        },
                    },
                    chunk_metrics,
                )

            chunk_file = temp_dir_path / (
                f"{input_path.stem}_part_{chunk_index:03d}.pdf"
            )
            lock_context = (
                cache_entry_lock(cache_dir / "chunks", chunk_cache_key)
                if chunk_cache_key and cache_dir is not None
                else None
            )
            try:
                if lock_context is not None:
                    lock_context.__enter__()
                if chunk_cache_key and cache_dir is not None:
                    cached, chunk_cache_path = load_cached_result(
                        cache_dir / "chunks",
                        chunk_cache_key,
                        expected_pages=end_page - start_page + 1,
                    )
                    if cached is not None:
                        print(
                            f"Using cached chunk {chunk_index}/{len(chunk_ranges)} "
                            f"pages {start_page}-{end_page}: {chunk_cache_path}",
                            file=sys.stderr,
                        )
                        chunk_metrics["chunk_cache_hits"] = 1.0
                        return chunk_index, cached, chunk_metrics
                    chunk_metrics["chunk_cache_misses"] = 1.0

                split_started_at = time.perf_counter()
                split_pdf(
                    input_path,
                    chunk_file,
                    f"{start_page}-{end_page}",
                )
                metric_add(
                    chunk_metrics,
                    "chunk_split_seconds",
                    time.perf_counter() - split_started_at,
                )
                chunk_result = parse_document(
                    file_path=str(chunk_file),
                    file_type=FILE_TYPE_PDF,
                    api_url=api_url,
                    token=token,
                    metrics=chunk_metrics,
                    expected_pages=end_page - start_page + 1,
                    deadline=deadline,
                    cancel_event=run_cancel,
                    allow_insecure_http=allow_insecure_http,
                    **options,
                )
                if (
                    chunk_cache_key
                    and cache_dir is not None
                    and chunk_result.get("ok")
                ):
                    save_cached_result(
                        cache_dir / "chunks",
                        chunk_cache_key,
                        chunk_result,
                        lock_held=lock_context is not None,
                    )
            except Exception as exc:
                chunk_result = {
                    "ok": False,
                    "text": "",
                    "result": None,
                    "error": {
                        "code": "CHUNK_ERROR",
                        "message": str(exc),
                    },
                }
            finally:
                chunk_file.unlink(missing_ok=True)
                if lock_context is not None:
                    lock_context.__exit__(None, None, None)

            if not chunk_result.get("ok"):
                error = chunk_result.setdefault("error", {})
                error["message"] = (
                    f"[chunk {chunk_index}/{len(chunk_ranges)}, "
                    f"pages {start_page}-{end_page}] "
                    f"{error.get('message', '')}"
                ).strip()
                error["message"] = append_chunk_retry_hint(
                    error["message"],
                    use_cache,
                )
            return chunk_index, chunk_result, chunk_metrics

        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=effective_workers
        )
        future_map = {
            executor.submit(parse_chunk_job, *job): job[0]
            for job in chunk_jobs
        }
        first_failure = None
        try:
            for future in concurrent.futures.as_completed(future_map):
                try:
                    chunk_index, chunk_result, chunk_metrics = future.result()
                except Exception as exc:
                    chunk_index = future_map[future]
                    chunk_result = {
                        "ok": False,
                        "text": "",
                        "result": None,
                        "error": {
                            "code": "CHUNK_ERROR",
                            "message": str(exc),
                        },
                    }
                    chunk_metrics = {}
                merge_metrics(metrics, chunk_metrics)
                if not chunk_result.get("ok"):
                    first_failure = chunk_result
                    run_cancel.set()
                    for pending in future_map:
                        if pending is not future:
                            pending.cancel()
                    break
                chunk_results_by_index[chunk_index] = chunk_result
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

        if first_failure is not None:
            return first_failure

        chunk_results = [
            chunk_results_by_index[index]
            for index in sorted(chunk_results_by_index)
        ]
        try:
            if _hash_file(input_path) != source_digest:
                return {
                    "ok": False,
                    "text": "",
                    "result": None,
                    "error": {
                        "code": "INPUT_ERROR",
                        "message": (
                            "Input PDF changed during OCR; refusing to publish "
                            "a mixed result"
                        ),
                    },
                }
        except OSError as exc:
            return {
                "ok": False,
                "text": "",
                "result": None,
                "error": {"code": "INPUT_ERROR", "message": str(exc)},
            }

    merge_started_at = time.perf_counter()
    try:
        return merge_chunk_results(
            chunk_results,
            chunk_ranges=chunk_ranges,
        )
    except (ValueError, OSError) as exc:
        return {
            "ok": False,
            "text": "",
            "result": None,
            "error": {"code": "API_ERROR", "message": str(exc)},
        }
    finally:
        metric_add(
            metrics,
            "merge_seconds",
            time.perf_counter() - merge_started_at,
        )
