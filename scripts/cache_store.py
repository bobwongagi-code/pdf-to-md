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

"""Content-addressed OCR cache and cache directory policy."""

import hashlib
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

from config import (
    FILE_TYPE_IMAGE,
    FILE_TYPE_PDF,
    IMAGE_EXTENSIONS,
    MAX_LOCAL_FILE_BYTES,
    _get_env,
    get_credential_scope_hash,
    get_cache_max_bytes,
    get_cache_ttl_seconds,
    get_endpoint_origin,
    get_max_pages_per_request,
)
from safe_io import atomic_write_json, file_lock
from version import VERSION

TOOL_VERSION = VERSION
CACHE_SCHEMA_VERSION = 3
MERGE_SCHEMA_VERSION = 2


def get_default_cache_dir() -> Path:
    return (
        Path(tempfile.gettempdir()) / "paddleocr" / "doc-parsing" / "cache"
    ).resolve()


def resolve_cache_dir(cache_dir_arg: Optional[str]) -> Path:
    if cache_dir_arg:
        return Path(cache_dir_arg).expanduser().resolve()
    return get_default_cache_dir()


def resolve_effective_file_type(
    file_path: str,
    file_type: Optional[int],
) -> Optional[int]:
    if file_type is not None:
        return file_type
    lower_path = file_path.lower()
    if lower_path.endswith(".pdf"):
        return FILE_TYPE_PDF
    if lower_path.endswith(IMAGE_EXTENSIONS):
        return FILE_TYPE_IMAGE
    return None


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        stat_before = os.fstat(source.fileno())
        if stat_before.st_size > MAX_LOCAL_FILE_BYTES:
            raise OSError(
                "Local source file exceeds the hard limit of "
                f"{MAX_LOCAL_FILE_BYTES // 1024 // 1024} MB"
            )
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
        stat_after = os.fstat(source.fileno())
    if (
        stat_before.st_size != stat_after.st_size
        or stat_before.st_ino != stat_after.st_ino
        or stat_before.st_dev != stat_after.st_dev
    ):
        raise OSError(f"File changed while hashing: {path}")
    return digest.hexdigest()


def build_cache_namespace(
    api_url: Optional[str],
    token: Optional[str],
) -> dict:
    return {
        "endpoint": api_url.rstrip("/") if api_url else "",
        "endpoint_origin": get_endpoint_origin(api_url) if api_url else "",
        "credential_scope_hash": (
            get_credential_scope_hash(token) if token else ""
        ),
        "tool_version": TOOL_VERSION,
        "cache_schema_version": CACHE_SCHEMA_VERSION,
        "merge_schema_version": MERGE_SCHEMA_VERSION,
    }


def build_cache_key(
    args,
    options: dict,
    api_url: Optional[str] = None,
    token: Optional[str] = None,
) -> Optional[str]:
    """Build a stable key for repeat parses of the same local file."""
    if not args.file_path:
        return None
    raw_path = Path(args.file_path).expanduser()
    if raw_path.is_symlink() and _get_env("PADDLEOCR_ALLOW_SYMLINKS").lower() not in {
        "1",
        "true",
        "yes",
    }:
        raise ValueError("symbolic-link inputs are disabled by default")
    path = raw_path.resolve()
    if not path.exists() or not path.is_file():
        return None
    if path.stat().st_size > MAX_LOCAL_FILE_BYTES:
        raise ValueError(
            "Local source file exceeds the hard limit of "
            f"{MAX_LOCAL_FILE_BYTES // 1024 // 1024} MB"
        )

    effective_chunk_pages = None
    if resolve_effective_file_type(str(path), args.file_type) == FILE_TYPE_PDF:
        effective_chunk_pages = get_max_pages_per_request(
            getattr(args, "chunk_pages", None)
        )
    payload = {
        "file_path": str(path),
        "content_digest": _hash_file(path),
        "file_type": resolve_effective_file_type(str(path), args.file_type),
        "options": options,
        "chunk_pages": effective_chunk_pages,
        "namespace": build_cache_namespace(api_url, token),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _cache_lock_path(cache_path: Path) -> Path:
    return cache_path.with_suffix(f"{cache_path.suffix}.lock")


def _cache_result_value(result: dict) -> dict:
    """Keep resume data without retaining provider raw JSON."""
    return {
        "ok": bool(result.get("ok")),
        "text": result.get("text", "")
        if isinstance(result.get("text"), str)
        else "",
        "coverage": result.get("coverage"),
        "assets": (
            result.get("assets", {})
            if isinstance(result.get("assets"), dict)
            else {}
        ),
        "result": None,
        "error": result.get("error"),
        "cache_raw_omitted": True,
    }


def _valid_cached_value(
    value: object,
    expected_pages: Optional[int] = None,
) -> bool:
    if not isinstance(value, dict) or value.get("ok") is not True:
        return False
    if not isinstance(value.get("text"), str) or not value["text"].strip():
        return False
    coverage = value.get("coverage")
    if not isinstance(coverage, dict) or coverage.get("complete") is not True:
        return False
    if coverage.get("partial") is not False:
        return False
    if coverage.get("missing_pages") != [] or coverage.get("duplicate_pages") != []:
        return False
    expected_coverage_pages = coverage.get("expected_pages")
    returned_pages = coverage.get("returned_pages")
    if not isinstance(expected_coverage_pages, int) or expected_coverage_pages < 1:
        return False
    if not isinstance(returned_pages, int) or returned_pages < 1:
        return False
    if expected_coverage_pages != returned_pages:
        return False
    if expected_pages is not None and returned_pages != expected_pages:
        return False
    return True


def cache_entry_lock(cache_dir: Path, cache_key: str):
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        cache_dir.chmod(0o700)
    except OSError:
        pass
    cache_path = cache_dir / f"{cache_key}.json"
    return file_lock(_cache_lock_path(cache_path))


def load_cached_result(
    cache_dir: Path,
    cache_key: str,
    expected_pages: Optional[int] = None,
):
    cache_path = cache_dir / f"{cache_key}.json"
    if not cache_path.exists():
        return None, cache_path
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "value" in payload:
            if payload.get("schema_version") != CACHE_SCHEMA_VERSION:
                cache_path.unlink(missing_ok=True)
                return None, cache_path
            expires_at = payload.get("expires_at")
            if not isinstance(expires_at, (int, float)) or not math.isfinite(
                expires_at
            ):
                cache_path.unlink(missing_ok=True)
                return None, cache_path
            if time.time() > expires_at:
                cache_path.unlink(missing_ok=True)
                return None, cache_path
            value = payload.get("value")
            if not _valid_cached_value(value, expected_pages):
                cache_path.unlink(missing_ok=True)
                return None, cache_path
            return value, cache_path
        cache_path.unlink(missing_ok=True)
        return None, cache_path
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"Warning: Ignoring corrupted cache file {cache_path}: {exc}",
            file=sys.stderr,
        )
        return None, cache_path


def _write_cached_result(cache_dir: Path, cache_key: str, result: dict):
    cache_path = cache_dir / f"{cache_key}.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.parent.chmod(0o700)
    atomic_write_json(
        cache_path,
        {
            "schema_version": CACHE_SCHEMA_VERSION,
            "expires_at": int(time.time()) + get_cache_ttl_seconds(),
            "value": _cache_result_value(result),
        },
        force=True,
    )
    return cache_path

def prune_cache(cache_dir: Path) -> None:
    """Bound cache growth by removing the oldest JSON entries."""
    if not cache_dir.is_dir():
        return
    entries = []
    total_bytes = 0
    for path in cache_dir.rglob("*.json"):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        total_bytes += size
        entries.append((path.stat().st_mtime, path, size))
    for _, path, size in sorted(entries):
        if total_bytes <= get_cache_max_bytes():
            break
        try:
            path.unlink()
            total_bytes -= size
        except OSError:
            continue


def save_cached_result(
    cache_dir: Path,
    cache_key: str,
    result: dict,
    *,
    lock_held: bool = False,
):
    if not _valid_cached_value(result):
        raise ValueError("Refusing to cache an incomplete or empty OCR result")
    if lock_held:
        path = _write_cached_result(cache_dir, cache_key, result)
    else:
        with cache_entry_lock(cache_dir, cache_key):
            path = _write_cached_result(cache_dir, cache_key, result)
    cache_dir.mkdir(parents=True, exist_ok=True)
    with file_lock(cache_dir / ".prune.lock"):
        prune_cache(cache_dir)
    return path


def build_chunk_cache_key(
    source_path: Path,
    start_page: int,
    end_page: int,
    file_type: Optional[int],
    options: dict,
    namespace: dict,
    content_digest: Optional[str] = None,
) -> str:
    payload = {
        "source_path": str(source_path),
        "content_digest": content_digest or _hash_file(source_path),
        "start_page": start_page,
        "end_page": end_page,
        "file_type": file_type,
        "options": options,
        "namespace": namespace,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
