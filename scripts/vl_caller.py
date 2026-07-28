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

"""Stable entry point for PaddleOCR PDF/image to Markdown conversion."""

import io
import logging
from pathlib import Path
import sys

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer,
        encoding="utf-8",
        errors="replace",
    )
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer,
        encoding="utf-8",
        errors="replace",
    )

if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

sys.path.insert(0, str(Path(__file__).parent))

# Keep the documented CLI and parser entry points explicit. The remaining
# imports below are compatibility exports for callers of the pre-split module.
__all__ = ("main", "parse_document", "__version__")

from artifacts import (  # noqa: E402
    collect_markdown_assets,
    extract_markdown_text,
    materialize_markdown_assets,
    resolve_assets_output_path,
    resolve_markdown_output_path,
    resolve_output_path,
    validate_markdown_output,
    write_json_file,
    write_markdown_file,
)
from cache_store import (  # noqa: E402
    CACHE_SCHEMA_VERSION,
    MERGE_SCHEMA_VERSION,
    TOOL_VERSION,
    _hash_file,
    build_cache_key,
    build_cache_namespace,
    build_chunk_cache_key,
    cache_entry_lock,
    get_default_cache_dir,
    load_cached_result,
    prune_cache,
    resolve_cache_dir,
    resolve_effective_file_type,
    save_cached_result,
)
from cli import (  # noqa: E402
    __version__,
    _main_impl,
    _parse_main_input,
    main,
    print_cli_error,
    print_timing_summary,
    timing_enabled,
)
from config import (  # noqa: E402
    DEFAULT_MAX_CHUNK_WORKERS,
    DEFAULT_MAX_PAGES_PER_REQUEST,
    FILE_TYPE_IMAGE,
    FILE_TYPE_PDF,
    MAX_LOCAL_FILE_BYTES,
    get_cache_max_bytes,
    get_cache_ttl_seconds,
    get_max_chunk_workers,
    get_max_pages_per_request,
    get_task_timeout_seconds,
)
from ocr_client import parse_document  # noqa: E402
from pipeline import (  # noqa: E402
    DEFAULT_MAX_TOTAL_PAGES,
    append_chunk_retry_hint,
    build_pdf_chunks,
    merge_chunk_results,
    merge_metrics,
    parse_with_auto_split,
)

if __name__ == "__main__":
    raise SystemExit(main())
