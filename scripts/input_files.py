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

"""Local file type detection and safe request payload preparation."""

import base64
import os
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

from config import (
    FILE_TYPE_IMAGE,
    FILE_TYPE_PDF,
    IMAGE_EXTENSIONS,
    MAX_LOCAL_FILE_BYTES,
    _get_env,
    _get_float_env,
)


def _detect_file_type(path_or_url: str) -> int:
    """Detect file type: 0=PDF, 1=Image."""
    path = path_or_url.lower()
    if path.startswith(("http://", "https://")):
        path = unquote(urlparse(path).path)
    if path.endswith(".pdf"):
        return FILE_TYPE_PDF
    if path.endswith(IMAGE_EXTENSIONS):
        return FILE_TYPE_IMAGE
    raise ValueError(f"Unsupported file format: {path_or_url}")


def _magic_matches_file_type(magic: bytes, file_type: int) -> bool:
    if file_type == FILE_TYPE_PDF:
        return magic.startswith(b"%PDF-")
    return (
        magic.startswith(b"\x89PNG\r\n\x1a\n")
        or magic.startswith(b"\xff\xd8\xff")
        or magic.startswith(b"BM")
        or magic.startswith(b"II*\x00")
        or magic.startswith(b"MM\x00*")
        or (magic.startswith(b"RIFF") and magic[8:12] == b"WEBP")
    )


def _load_file_as_base64(
    file_path: str,
    expected_file_type: Optional[int] = None,
) -> str:
    """Read a stable local file and encode it as base64."""
    path = Path(file_path).expanduser()
    if path.is_symlink() and _get_env("PADDLEOCR_ALLOW_SYMLINKS").lower() not in {
        "1",
        "true",
        "yes",
    }:
        raise ValueError(f"Symbolic links are not accepted by default: {file_path}")
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if not path.is_file():
        raise ValueError(f"Not a file: {file_path}")

    warning_threshold_mb = _get_float_env(
        "PADDLEOCR_DOC_PARSING_LARGE_FILE_WARNING_MB",
        50,
        min_value=1,
        max_value=10240,
    )
    warning_threshold_bytes = int(warning_threshold_mb * 1024 * 1024)
    with path.open("rb") as source:
        stat_before = os.fstat(source.fileno())
        if stat_before.st_size <= 0:
            raise ValueError(f"File is empty: {file_path}")
        max_file_mb = _get_float_env(
            "PADDLEOCR_DOC_PARSING_MAX_LOCAL_FILE_MB",
            200,
            min_value=1,
            max_value=MAX_LOCAL_FILE_BYTES / 1024 / 1024,
        )
        max_file_bytes = int(max_file_mb * 1024 * 1024)
        if stat_before.st_size > max_file_bytes:
            raise ValueError(
                f"Local file is too large ({stat_before.st_size / 1024 / 1024:.1f} MB); "
                f"maximum is {max_file_mb:g} MB. Use --file-url or split the file."
            )
        if stat_before.st_size >= warning_threshold_bytes:
            import logging

            logging.getLogger(__name__).warning(
                "Large local file detected (%.1f MB): %s. Prefer --file-url when "
                "possible to avoid base64 overhead.",
                stat_before.st_size / 1024 / 1024,
                file_path,
            )
        magic = source.read(16)
        if expected_file_type is not None and not _magic_matches_file_type(
            magic, expected_file_type
        ):
            expected_name = "PDF" if expected_file_type == FILE_TYPE_PDF else "image"
            raise ValueError(
                f"File content does not match the requested {expected_name} type"
            )
        source.seek(0)
        raw = source.read(max_file_bytes + 1)
        stat_after = os.fstat(source.fileno())
        if (
            stat_after.st_size != stat_before.st_size
            or stat_after.st_ino != stat_before.st_ino
        ):
            raise ValueError(
                "File changed while it was being read; refusing to upload it"
            )
        if len(raw) != stat_before.st_size:
            raise ValueError(
                "Could not read the complete file; refusing to upload it"
            )
        return base64.b64encode(raw).decode("ascii")
