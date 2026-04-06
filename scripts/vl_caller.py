#!/usr/bin/env python3
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

"""
PaddleOCR Document Parser

Simple CLI wrapper for the PaddleOCR document parsing library.

Usage:
    python scripts/paddleocr-doc-parsing/vl_caller.py --file-url "URL"
    python scripts/paddleocr-doc-parsing/vl_caller.py --file-path "document.pdf"
    python scripts/paddleocr-doc-parsing/vl_caller.py --file-path "doc.pdf" --pretty
"""

import argparse
import concurrent.futures
import hashlib
import io
import json
import logging
import os
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

# Add scripts dir to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from lib import FILE_TYPE_IMAGE, FILE_TYPE_PDF, parse_document
from split_pdf import get_pdf_page_count, split_pdf

__version__ = "2.0.8"
DEFAULT_MAX_PAGES_PER_REQUEST = 100
DEFAULT_MAX_CHUNK_WORKERS = 2
DEFAULT_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60


def metric_add(metrics: Optional[dict[str, float]], key: str, delta: float) -> None:
    if metrics is None:
        return
    metrics[key] = metrics.get(key, 0.0) + delta


def merge_metrics(
    target: Optional[dict[str, float]],
    source: Optional[dict[str, float]],
) -> None:
    if target is None or source is None:
        return
    for key, value in source.items():
        target[key] = target.get(key, 0.0) + value


def timing_enabled(args: argparse.Namespace) -> bool:
    if getattr(args, "timing", False):
        return True
    return os.getenv("PADDLEOCR_DOC_PARSING_TIMING", "").strip() in {"1", "true", "TRUE", "yes", "YES"}


def print_timing_summary(metrics: Optional[dict[str, float]]) -> None:
    if not metrics:
        return
    print("Timing summary:", file=sys.stderr)
    for key in sorted(metrics):
        value = metrics[key]
        if key.endswith("_count") or key.endswith("_hits") or key.endswith("_misses"):
            print(f"  {key}: {int(value)}", file=sys.stderr)
        else:
            print(f"  {key}: {value:.3f}s", file=sys.stderr)


def get_default_output_path():
    """Build a unique result path under the OS temp directory."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    short_id = uuid.uuid4().hex[:8]
    return (
        Path(tempfile.gettempdir())
        / "paddleocr"
        / "doc-parsing"
        / "results"
        / f"result_{timestamp}_{short_id}.json"
    )


def resolve_output_path(output_arg):
    if output_arg:
        return Path(output_arg).expanduser().resolve()
    return get_default_output_path().resolve()


def get_default_cache_dir():
    return (
        Path(tempfile.gettempdir()) / "paddleocr" / "doc-parsing" / "cache"
    ).resolve()


def resolve_cache_dir(cache_dir_arg):
    if cache_dir_arg:
        return Path(cache_dir_arg).expanduser().resolve()
    return get_default_cache_dir()


def resolve_effective_file_type(file_path: str, file_type: Optional[int]) -> Optional[int]:
    if file_type is not None:
        return file_type
    lower_path = file_path.lower()
    if lower_path.endswith(".pdf"):
        return FILE_TYPE_PDF
    if lower_path.endswith((".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp")):
        return FILE_TYPE_IMAGE
    return None


def get_cache_ttl_seconds() -> int:
    return max(
        1,
        int(
            os.getenv(
                "PADDLEOCR_DOC_PARSING_CACHE_TTL_SECONDS",
                DEFAULT_CACHE_TTL_SECONDS,
            )
        ),
    )


def build_cache_key(args, options: dict) -> Optional[str]:
    """Build a stable cache key for repeat parses of the same local file."""
    if not args.file_path:
        return None

    path = Path(args.file_path).expanduser().resolve()
    if not path.exists() or not path.is_file():
        return None

    stat = path.stat()
    payload = {
        "file_path": str(path),
        "file_size": stat.st_size,
        "file_mtime_ns": stat.st_mtime_ns,
        "file_type": resolve_effective_file_type(str(path), args.file_type),
        "options": options,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return digest


def load_cached_result(cache_dir: Path, cache_key: str):
    cache_path = cache_dir / f"{cache_key}.json"
    if not cache_path.exists():
        return None, cache_path
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "value" in payload:
            expires_at = payload.get("expires_at")
            if isinstance(expires_at, (int, float)) and time.time() > expires_at:
                cache_path.unlink(missing_ok=True)
                return None, cache_path
            return payload.get("value"), cache_path
        return payload, cache_path
    except (OSError, json.JSONDecodeError) as e:
        print(f"Warning: Ignoring corrupted cache file {cache_path}: {e}", file=sys.stderr)
        return None, cache_path


def save_cached_result(cache_dir: Path, cache_key: str, result: dict):
    cache_path = cache_dir / f"{cache_key}.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = cache_path.with_suffix(f"{cache_path.suffix}.tmp")
    with temp_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "expires_at": int(time.time()) + get_cache_ttl_seconds(),
                "value": result,
            },
            f,
            ensure_ascii=False,
        )
    os.replace(temp_path, cache_path)
    return cache_path


def build_chunk_cache_key(
    source_path: Path,
    start_page: int,
    end_page: int,
    file_type: Optional[int],
    options: dict,
) -> str:
    stat = source_path.stat()
    payload = {
        "source_path": str(source_path),
        "source_size": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
        "start_page": start_page,
        "end_page": end_page,
        "file_type": file_type,
        "options": options,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def build_pdf_chunks(total_pages: int, chunk_size: int) -> list[tuple[int, int]]:
    return [
        (start, min(start + chunk_size - 1, total_pages))
        for start in range(1, total_pages + 1, chunk_size)
    ]


def merge_chunk_results(chunk_results: list[dict]) -> dict:
    if not chunk_results:
        raise ValueError("No chunk results to merge")

    merged = chunk_results[0]
    merged_texts = []
    merged_pages = []

    for chunk_result in chunk_results:
        if not chunk_result.get("ok"):
            return chunk_result
        if chunk_result.get("text"):
            merged_texts.append(chunk_result["text"])
        raw_result = chunk_result.get("result")
        if not isinstance(raw_result, dict):
            raise ValueError("Chunk result missing result object")
        nested_result = raw_result.get("result")
        if not isinstance(nested_result, dict):
            raise ValueError("Chunk result missing result.result object")
        pages = nested_result.get("layoutParsingResults")
        if not isinstance(pages, list):
            raise ValueError("Chunk result missing result.result.layoutParsingResults")
        merged_pages.extend(pages)

    merged["text"] = "\n\n".join(text for text in merged_texts if text)
    merged["result"]["result"]["layoutParsingResults"] = merged_pages
    merged["error"] = None
    merged["ok"] = True
    return merged


def parse_with_auto_split(
    file_path: str,
    file_type: Optional[int],
    cache_dir: Optional[Path] = None,
    use_cache: bool = True,
    api_url: Optional[str] = None,
    token: Optional[str] = None,
    metrics: Optional[dict[str, float]] = None,
    **options,
) -> dict:
    resolved_file_type = file_type
    if resolved_file_type is None and file_path.lower().endswith(".pdf"):
        resolved_file_type = FILE_TYPE_PDF

    if resolved_file_type != FILE_TYPE_PDF:
        return parse_document(
            file_path=file_path,
            file_type=file_type,
            api_url=api_url,
            token=token,
            **options,
        )

    input_path = Path(file_path).expanduser().resolve()
    page_count_started_at = time.perf_counter()
    try:
        total_pages = get_pdf_page_count(input_path)
    except RuntimeError as e:
        return {
            "ok": False,
            "text": "",
            "result": None,
            "error": {"code": "INPUT_ERROR", "message": str(e)},
        }
    finally:
        metric_add(metrics, "page_count_seconds", time.perf_counter() - page_count_started_at)

    if total_pages <= DEFAULT_MAX_PAGES_PER_REQUEST:
        return parse_document(
            file_path=str(input_path),
            file_type=file_type,
            api_url=api_url,
            token=token,
            metrics=metrics,
            **options,
        )

    chunk_ranges = build_pdf_chunks(total_pages, DEFAULT_MAX_PAGES_PER_REQUEST)
    print(
        (
            f"Large PDF detected ({total_pages} pages). "
            f"Splitting into {len(chunk_ranges)} chunk(s) of up to "
            f"{DEFAULT_MAX_PAGES_PER_REQUEST} pages."
        ),
        file=sys.stderr,
    )

    max_chunk_workers = max(
        1,
        int(
            os.getenv(
                "PADDLEOCR_DOC_PARSING_MAX_CHUNK_WORKERS",
                DEFAULT_MAX_CHUNK_WORKERS,
            )
        ),
    )
    effective_workers = min(max_chunk_workers, len(chunk_ranges))

    with tempfile.TemporaryDirectory(prefix="paddleocr_split_") as temp_dir:
        temp_dir_path = Path(temp_dir)
        chunk_jobs: list[tuple[int, int, int, Optional[str], Optional[Path]]] = []
        chunk_results_by_index = {}

        for chunk_index, (start_page, end_page) in enumerate(chunk_ranges, start=1):
            chunk_cache_key = None
            chunk_result = None
            chunk_file = None
            if use_cache and cache_dir is not None:
                chunk_cache_key = build_chunk_cache_key(
                    input_path,
                    start_page,
                    end_page,
                    FILE_TYPE_PDF,
                    options,
                )
                chunk_result, chunk_cache_path = load_cached_result(
                    cache_dir / "chunks", chunk_cache_key
                )
                if chunk_result is not None:
                    print(
                        (
                            f"Using cached chunk {chunk_index}/{len(chunk_ranges)} "
                            f"pages {start_page}-{end_page}: {chunk_cache_path}"
                        ),
                        file=sys.stderr,
                    )
                    merge_metrics(metrics, {"chunk_cache_hits": 1.0})
                    chunk_results_by_index[chunk_index] = chunk_result
                    continue

            merge_metrics(metrics, {"chunk_cache_misses": 1.0})
            chunk_file = temp_dir_path / f"{input_path.stem}_part_{chunk_index:03d}.pdf"
            pages_spec = f"{start_page}-{end_page}"
            split_started_at = time.perf_counter()
            try:
                split_pdf(input_path, chunk_file, pages_spec)
            except RuntimeError as e:
                return {
                    "ok": False,
                    "text": "",
                    "result": None,
                    "error": {
                        "code": "INPUT_ERROR",
                        "message": (
                            f"[chunk {chunk_index}/{len(chunk_ranges)}, pages {start_page}-{end_page}] {e}"
                        ),
                    },
                }
            finally:
                metric_add(metrics, "chunk_split_seconds", time.perf_counter() - split_started_at)
            chunk_jobs.append((chunk_index, start_page, end_page, chunk_cache_key, chunk_file))

        def parse_chunk_job(
            chunk_index: int,
            start_page: int,
            end_page: int,
            chunk_cache_key: Optional[str],
            chunk_file: Path,
            client: httpx.Client,
        ) -> tuple[int, dict, dict[str, float]]:
            chunk_metrics = {"chunk_parse_count": 1.0}
            print(
                (
                    f"Parsing chunk {chunk_index}/{len(chunk_ranges)} "
                    f"pages {start_page}-{end_page}"
                ),
                file=sys.stderr,
            )
            chunk_result = parse_document(
                file_path=str(chunk_file),
                file_type=FILE_TYPE_PDF,
                api_url=api_url,
                token=token,
                client=client,
                metrics=chunk_metrics,
                **options,
            )
            if (
                chunk_cache_key
                and cache_dir is not None
                and chunk_result.get("ok")
            ):
                try:
                    save_cached_result(cache_dir / "chunks", chunk_cache_key, chunk_result)
                except OSError as e:
                    print(f"Warning: Failed to update chunk cache: {e}", file=sys.stderr)
            if not chunk_result.get("ok"):
                err = chunk_result.setdefault("error", {})
                err["message"] = (
                    f"[chunk {chunk_index}/{len(chunk_ranges)}, "
                    f"pages {start_page}-{end_page}] {err.get('message', '')}".strip()
                )
            return chunk_index, chunk_result, chunk_metrics

        with httpx.Client(follow_redirects=True) as client:
            with concurrent.futures.ThreadPoolExecutor(max_workers=effective_workers) as executor:
                future_map = {
                    executor.submit(
                        parse_chunk_job,
                        chunk_index,
                        start_page,
                        end_page,
                        chunk_cache_key,
                        chunk_file,
                        client,
                    ): chunk_index
                    for chunk_index, start_page, end_page, chunk_cache_key, chunk_file in chunk_jobs
                }
                for future in concurrent.futures.as_completed(future_map):
                    chunk_index, chunk_result, chunk_metrics = future.result()
                    merge_metrics(metrics, chunk_metrics)
                    if not chunk_result.get("ok"):
                        return chunk_result
                    chunk_results_by_index[chunk_index] = chunk_result

        chunk_results = [
            chunk_results_by_index[idx] for idx in sorted(chunk_results_by_index)
        ]

    merge_started_at = time.perf_counter()
    try:
        return merge_chunk_results(chunk_results)
    except ValueError as e:
        return {
            "ok": False,
            "text": "",
            "result": None,
            "error": {"code": "API_ERROR", "message": str(e)},
        }
    finally:
        metric_add(metrics, "merge_seconds", time.perf_counter() - merge_started_at)


def main():
    parser = argparse.ArgumentParser(
        description="PaddleOCR Document Parsing - with layout analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Parse document from URL (result is auto-saved to the system temp directory)
  python scripts/paddleocr-doc-parsing/vl_caller.py --file-url "https://example.com/document.pdf"

  # Parse local file (result is auto-saved to the system temp directory)
  python scripts/paddleocr-doc-parsing/vl_caller.py --file-path "./invoice.pdf"

  # Save result to a custom file path
  python scripts/paddleocr-doc-parsing/vl_caller.py --file-url "URL" --output "./result.json" --pretty

  # Print JSON to stdout without saving a file
  python scripts/paddleocr-doc-parsing/vl_caller.py --file-url "URL" --stdout --pretty
Configuration:
  Set environment variables: PADDLEOCR_DOC_PARSING_API_URL, PADDLEOCR_ACCESS_TOKEN
  Optional: PADDLEOCR_DOC_PARSING_TIMEOUT
        """,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    # Input (mutually exclusive, required)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--file-url", help="URL to document (PDF, PNG, JPG, etc.)")
    input_group.add_argument("--file-path", help="Local file path")

    # Optional input options
    parser.add_argument(
        "--file-type",
        type=int,
        choices=[0, 1],
        help="Optional file type override (0=PDF, 1=Image)",
    )

    # Output options
    parser.add_argument(
        "--pretty", action="store_true", help="Pretty-print JSON output"
    )
    parser.add_argument(
        "--doc-unwarping",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable document unwarping for warped/scanned pages.",
    )
    parser.add_argument(
        "--orientation-classify",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable document orientation classification before parsing.",
    )
    parser.add_argument(
        "--timing",
        action="store_true",
        help="Print phase timing details to stderr for profiling.",
    )
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--output",
        "-o",
        metavar="FILE",
        help="Save result to JSON file (default: auto-save to system temp directory)",
    )
    output_group.add_argument(
        "--stdout",
        action="store_true",
        help="Print JSON to stdout instead of saving to a file",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable local cache for repeated local-file parses",
    )
    parser.add_argument(
        "--cache-dir",
        metavar="DIR",
        help="Custom cache directory for local-file parse results",
    )

    args = parser.parse_args()
    total_started_at = time.perf_counter()
    cache_dir = resolve_cache_dir(args.cache_dir)
    parse_options = {
        "useDocUnwarping": bool(args.doc_unwarping),
        "useDocOrientationClassify": bool(args.orientation_classify),
        "visualize": False,
    }
    metrics: Optional[dict[str, float]] = {} if timing_enabled(args) else None
    api_url = None
    token = None
    config_started_at = time.perf_counter()
    try:
        from lib import get_config

        api_url, token = get_config()
    except ValueError:
        # parse_document will preserve the established CONFIG_ERROR behavior
        pass
    finally:
        metric_add(metrics, "config_lookup_seconds", time.perf_counter() - config_started_at)

    if args.file_path:
        input_path = Path(args.file_path).expanduser()
        if not input_path.exists():
            print(f"Error: File not found: {input_path}", file=sys.stderr)
            sys.exit(2)
        if not input_path.is_file():
            print(f"Error: Not a file: {input_path}", file=sys.stderr)
            sys.exit(2)

    result = None
    cache_key = None
    cache_path = None
    if not args.no_cache:
        cache_key = build_cache_key(args, parse_options)
        if cache_key:
            cache_lookup_started_at = time.perf_counter()
            result, cache_path = load_cached_result(cache_dir, cache_key)
            metric_add(metrics, "full_cache_lookup_seconds", time.perf_counter() - cache_lookup_started_at)
            if result is not None:
                metric_add(metrics, "full_cache_hits", 1.0)
            else:
                metric_add(metrics, "full_cache_misses", 1.0)

    if result is None:
        # Parse document
        if args.file_path:
            result = parse_with_auto_split(
                file_path=args.file_path,
                file_type=args.file_type,
                cache_dir=cache_dir if cache_key else None,
                use_cache=not args.no_cache,
                api_url=api_url,
                token=token,
                metrics=metrics,
                **parse_options,
            )
        else:
            result = parse_document(
                file_url=args.file_url,
                file_type=args.file_type,
                api_url=api_url,
                token=token,
                metrics=metrics,
                **parse_options,
            )
        if cache_key and result.get("ok"):
            try:
                save_cached_result(cache_dir, cache_key, result)
            except OSError as e:
                print(f"Warning: Failed to update cache: {e}", file=sys.stderr)
    elif cache_path:
        print(f"Using cached result: {cache_path}", file=sys.stderr)

    # Format output
    indent = 2 if args.pretty else None
    if args.stdout:
        print(json.dumps(result, indent=indent, ensure_ascii=False))
    else:
        output_path = resolve_output_path(args.output)

        # Save to file
        output_write_started_at = time.perf_counter()
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
            with temp_path.open("w", encoding="utf-8") as f:
                json.dump(result, f, indent=indent, ensure_ascii=False)
            os.replace(temp_path, output_path)
            print(f"Result saved to: {output_path}", file=sys.stderr)
        except (PermissionError, OSError) as e:
            print(f"Error: Cannot write to {output_path}: {e}", file=sys.stderr)
            sys.exit(5)
        finally:
            metric_add(metrics, "output_write_seconds", time.perf_counter() - output_write_started_at)

    # Exit code based on result
    metric_add(metrics, "total_seconds", time.perf_counter() - total_started_at)
    if timing_enabled(args):
        print_timing_summary(metrics)
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
