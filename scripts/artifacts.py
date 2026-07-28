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

"""Markdown, JSON, and provider image artifact handling."""

import base64
from datetime import datetime
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

from config import (
    _get_float_env,
    get_asset_total_timeout_seconds,
    get_max_asset_count,
    get_max_asset_total_bytes,
)
from response_parser import _extract_markdown_assets
from safe_io import (
    OutputPathError,
    atomic_replace,
    atomic_replace_directory,
    atomic_write_json,
    atomic_write_text,
    paths_collide,
)

DEFAULT_ASSET_TIMEOUT = 60
MAX_ASSET_BYTES = 32 * 1024 * 1024


def get_default_output_path() -> Path:
    """Build a unique result path under the OS temporary directory."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    short_id = uuid.uuid4().hex[:8]
    return (
        Path(tempfile.gettempdir())
        / "paddleocr"
        / "doc-parsing"
        / "results"
        / f"result_{timestamp}_{short_id}.json"
    )


def resolve_output_path(output_arg: Optional[str]) -> Path:
    if output_arg:
        return Path(output_arg).expanduser().absolute()
    return get_default_output_path().absolute()


def resolve_markdown_output_path(
    markdown_output_arg: Optional[str],
    input_file_path: Optional[str],
) -> Optional[Path]:
    if markdown_output_arg:
        return Path(markdown_output_arg).expanduser().absolute()
    if input_file_path:
        input_path = Path(input_file_path).expanduser().resolve()
        return input_path.with_name(f"{input_path.name}.md")
    return None


def resolve_assets_output_path(
    assets_output_arg: Optional[str],
    markdown_path: Optional[Path],
) -> Optional[Path]:
    if markdown_path is None:
        return (
            Path(assets_output_arg).expanduser().resolve()
            if assets_output_arg
            else None
        )
    if assets_output_arg:
        return Path(assets_output_arg).expanduser().absolute()
    return markdown_path.with_name(f"{markdown_path.stem}.assets").absolute()


def extract_markdown_text(result: dict) -> str:
    text = result.get("text")
    return text if isinstance(text, str) else ""


def write_json_file(
    output_path: Path,
    result: dict,
    indent: Optional[int],
    *,
    force: bool = False,
) -> None:
    atomic_write_json(output_path, result, indent=indent, force=force)


def write_markdown_file(
    output_path: Path,
    markdown_text: str,
    *,
    force: bool = False,
) -> None:
    content = (
        markdown_text
        if markdown_text.endswith("\n")
        else f"{markdown_text}\n"
    )
    atomic_write_text(output_path, content, force=force)


def validate_markdown_output(result: dict) -> tuple[bool, str]:
    if not result.get("ok"):
        error = result.get("error") or {}
        message = error.get("message") if isinstance(error, dict) else None
        return False, message or "parse failed"
    markdown_text = extract_markdown_text(result).strip()
    if not markdown_text:
        return False, "parse succeeded but extracted Markdown text is empty"
    return True, ""


def collect_markdown_assets(result: dict) -> dict[str, str]:
    assets = result.get("assets") if isinstance(result, dict) else None
    if isinstance(assets, dict):
        return {str(key): str(value) for key, value in assets.items()}
    raw_result = result.get("result") if isinstance(result, dict) else None
    if isinstance(raw_result, dict) and raw_result.get("type") == "chunked_ocr":
        merged: dict[str, str] = {}
        for chunk in raw_result.get("chunks", []):
            provider_response = (
                chunk.get("provider_response")
                if isinstance(chunk, dict)
                else None
            )
            if isinstance(provider_response, dict):
                merged.update(_extract_markdown_assets(provider_response))
        return merged
    if isinstance(raw_result, dict):
        return _extract_markdown_assets(raw_result)
    return {}


def _asset_bytes(source: str) -> tuple[bytes, str]:
    if source.startswith("data:"):
        header, separator, payload = source.partition(",")
        if not separator or ";base64" not in header:
            raise ValueError("Only base64 data URI Markdown assets are supported")
        try:
            data = base64.b64decode(payload, validate=True)
        except ValueError as exc:
            raise ValueError("Invalid base64 Markdown asset") from exc
        if len(data) > MAX_ASSET_BYTES:
            raise ValueError("Markdown asset exceeds the 32 MB limit")
        media_type = header[5:].split(";", 1)[0] or "application/octet-stream"
        return data, media_type

    parsed = urlparse(source)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Markdown assets must use HTTPS URLs or base64 data URIs")
    timeout = _get_float_env(
        "PADDLEOCR_DOC_PARSING_ASSET_TIMEOUT",
        DEFAULT_ASSET_TIMEOUT,
        min_value=1,
        max_value=300,
    )
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        with client.stream("GET", source) as response:
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    declared_length = int(content_length)
                except ValueError:
                    declared_length = None
                if declared_length is not None and declared_length > MAX_ASSET_BYTES:
                    raise ValueError("Markdown asset exceeds the 32 MB limit")
            if response.status_code != 200:
                raise RuntimeError(
                    f"Markdown asset download failed with HTTP {response.status_code}"
                )
            chunks = []
            total_bytes = 0
            for chunk in response.iter_bytes():
                total_bytes += len(chunk)
                if total_bytes > MAX_ASSET_BYTES:
                    raise ValueError("Markdown asset exceeds the 32 MB limit")
                chunks.append(chunk)
            return b"".join(chunks), response.headers.get(
                "Content-Type",
                "application/octet-stream",
            )


def _replace_asset_reference(
    markdown_text: str,
    source_name: str,
    replacement: str,
) -> str:
    """Rewrite only Markdown/HTML image references, never arbitrary text."""
    escaped_source = re.escape(source_name)
    rewritten = markdown_text
    markdown_pattern = re.compile(
        rf"(?P<prefix>(?:!?)\[[^\]]*\]\(\s*)"
        rf"{escaped_source}"
        rf"(?P<suffix>\s*(?:[\"'][^)]*[\"'])?\s*\))"
    )
    rewritten = markdown_pattern.sub(
        lambda match: f"{match.group('prefix')}{replacement}{match.group('suffix')}",
        rewritten,
    )
    html_pattern = re.compile(
        rf"(?P<prefix><img\b[^>]*?\bsrc=[\"'])"
        rf"{escaped_source}"
        rf"(?P<suffix>[\"'])",
        flags=re.IGNORECASE,
    )
    return html_pattern.sub(
        lambda match: f"{match.group('prefix')}{replacement}{match.group('suffix')}",
        rewritten,
    )


def materialize_markdown_assets(
    result: dict,
    markdown_path: Path,
    *,
    force: bool = False,
    asset_dir: Optional[Path] = None,
    asset_reference_name: Optional[str] = None,
) -> str:
    """Download provider image resources and rewrite Markdown references safely."""
    assets = collect_markdown_assets(result)
    text = extract_markdown_text(result)
    asset_dir = (
        asset_dir.expanduser().absolute()
        if asset_dir is not None
        else markdown_path.with_name(f"{markdown_path.stem}.assets")
    )
    reference_name = asset_reference_name or asset_dir.name
    reference_path = Path(reference_name)
    if (
        reference_path.name != reference_name
        or reference_name in {"", ".", ".."}
    ):
        raise OutputPathError(
            "Markdown asset reference must be a single directory name"
        )
    if paths_collide(asset_dir, markdown_path):
        raise OutputPathError(
            "Markdown asset directory collides with Markdown output"
        )
    if os.path.lexists(str(asset_dir)) and not force and assets:
        raise OutputPathError(
            f"Markdown asset directory already exists: {asset_dir} "
            "(use --force to overwrite)"
        )
    if not assets:
        if force and os.path.lexists(str(asset_dir)):
            if asset_dir.is_dir() and not asset_dir.is_symlink():
                shutil.rmtree(asset_dir, ignore_errors=True)
            else:
                asset_dir.unlink(missing_ok=True)
        return text

    unique_sources = set(assets.values())
    max_asset_count = get_max_asset_count()
    if len(unique_sources) > max_asset_count:
        raise ValueError(
            f"Markdown asset count exceeds the {max_asset_count} asset limit"
        )
    max_asset_total_bytes = get_max_asset_total_bytes()
    asset_deadline = time.monotonic() + get_asset_total_timeout_seconds()

    asset_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = asset_dir.parent / (
        f".{asset_dir.name}.staging-{uuid.uuid4().hex}"
    )
    staging_dir.mkdir(parents=True)
    staging_dir.chmod(0o700)
    rewritten = text
    source_filenames: dict[str, str] = {}
    total_asset_bytes = 0
    try:
        for source_name, source in assets.items():
            filename = source_filenames.get(source)
            if filename is None:
                if time.monotonic() > asset_deadline:
                    raise TimeoutError("Markdown asset download time limit exceeded")
                data, media_type = _asset_bytes(source)
                total_asset_bytes += len(data)
                if total_asset_bytes > max_asset_total_bytes:
                    raise ValueError(
                        "Markdown assets exceed the total size limit of "
                        f"{max_asset_total_bytes // 1024 // 1024} MB"
                    )
                extension = Path(urlparse(source).path).suffix.lower()
                if (
                    not extension
                    or len(extension) > 8
                    or not extension[1:].isalnum()
                ):
                    extension = {
                        "image/png": ".png",
                        "image/jpeg": ".jpg",
                        "image/webp": ".webp",
                        "image/tiff": ".tiff",
                    }.get(media_type.split(";", 1)[0], ".bin")
                filename = (
                    f"{hashlib.sha256(source.encode('utf-8')).hexdigest()[:16]}"
                    f"{extension}"
                )
                asset_path = staging_dir / filename
                fd, temp_name = tempfile.mkstemp(
                    prefix=f".{filename}.",
                    suffix=".tmp",
                    dir=str(staging_dir),
                )
                temp_path = Path(temp_name)
                try:
                    with os.fdopen(fd, "wb") as output:
                        output.write(data)
                        output.flush()
                        os.fsync(output.fileno())
                    atomic_replace(temp_path, asset_path, force=False)
                finally:
                    temp_path.unlink(missing_ok=True)
                source_filenames[source] = filename
            rewritten = _replace_asset_reference(
                rewritten,
                source_name,
                f"{reference_name}/{filename}",
            )
        atomic_replace_directory(staging_dir, asset_dir, force=force)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    return rewritten
