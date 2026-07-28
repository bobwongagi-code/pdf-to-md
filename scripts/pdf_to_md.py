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
Thin wrapper for the common local-file PDF-to-Markdown workflow.

Usage:
    python scripts/pdf_to_md.py /absolute/path/to/document.pdf
    python scripts/pdf_to_md.py /absolute/path/to/document.pdf --markdown-output /tmp/doc.md
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

import vl_caller


def build_vl_args(args: argparse.Namespace) -> list[str]:
    vl_args = [
        "vl_caller.py",
        "--file-path",
        str(Path(args.file_path).expanduser()),
        "--write-markdown",
    ]
    if args.markdown_output:
        vl_args.extend(["--markdown-output", args.markdown_output])
    if getattr(args, "force", False):
        vl_args.append("--force")
    if getattr(args, "allow_insecure_http", False):
        vl_args.append("--allow-insecure-http")
    if getattr(args, "no_assets", False):
        vl_args.append("--no-assets")
    if getattr(args, "assets_output", None):
        vl_args.extend(["--assets-output", args.assets_output])
    if getattr(args, "assets_reference_name", None):
        vl_args.extend(["--assets-reference-name", args.assets_reference_name])
    if args.file_type is not None:
        vl_args.extend(["--file-type", str(args.file_type)])
    if args.pretty:
        vl_args.append("--pretty")
    if args.doc_unwarping:
        vl_args.append("--doc-unwarping")
    if args.orientation_classify:
        vl_args.append("--orientation-classify")
    if args.no_cache:
        vl_args.append("--no-cache")
    if args.cache_dir:
        vl_args.extend(["--cache-dir", args.cache_dir])
    if args.chunk_pages:
        vl_args.extend(["--chunk-pages", str(args.chunk_pages)])
    if args.chunk_workers:
        vl_args.extend(["--chunk-workers", str(args.chunk_workers)])
    if args.output:
        vl_args.extend(["--output", args.output])
    if getattr(args, "keep_raw", False):
        vl_args.append("--keep-raw")
    if args.timing:
        vl_args.append("--timing")
    return vl_args


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert a local PDF or document image to Markdown with sensible defaults.",
    )
    parser.add_argument("file_path", help="Local PDF or image path")
    parser.add_argument(
        "--markdown-output",
        metavar="FILE",
        help="Optional explicit Markdown output path",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing outputs")
    parser.add_argument(
        "--allow-insecure-http",
        action="store_true",
        help="Allow HTTP only for loopback development endpoints",
    )
    parser.add_argument(
        "--no-assets",
        action="store_true",
        help="Do not download image resources referenced by Markdown",
    )
    parser.add_argument(
        "--assets-output",
        metavar="DIR",
        help="Directory for downloaded Markdown image resources",
    )
    parser.add_argument(
        "--assets-reference-name",
        metavar="NAME",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--output",
        "-o",
        metavar="FILE",
        help="Optional JSON output path",
    )
    parser.add_argument(
        "--keep-raw",
        action="store_true",
        help="Keep raw provider JSON at the default temporary output path",
    )
    parser.add_argument(
        "--file-type",
        type=int,
        choices=[0, 1],
        help="Optional file type override (0=PDF, 1=Image)",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print saved JSON output")
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
    parser.add_argument("--timing", action="store_true", help="Print timing details to stderr")
    parser.add_argument("--no-cache", action="store_true", help="Disable local cache")
    parser.add_argument("--cache-dir", metavar="DIR", help="Custom cache directory")
    parser.add_argument(
        "--chunk-pages",
        type=int,
        metavar="N",
        help="Pages per PDF OCR chunk for large local PDFs",
    )
    parser.add_argument(
        "--chunk-workers",
        type=int,
        metavar="N",
        help="Concurrent PDF OCR chunks for large local PDFs",
    )

    args = parser.parse_args(argv)
    return vl_caller.main(build_vl_args(args)[1:])


if __name__ == "__main__":
    raise SystemExit(main())
