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
    if args.output:
        vl_args.extend(["--output", args.output])
    if args.timing:
        vl_args.append("--timing")
    return vl_args


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a local PDF or document image to Markdown with sensible defaults.",
    )
    parser.add_argument("file_path", help="Local PDF or image path")
    parser.add_argument(
        "--markdown-output",
        metavar="FILE",
        help="Optional explicit Markdown output path",
    )
    parser.add_argument(
        "--output",
        "-o",
        metavar="FILE",
        help="Optional JSON output path",
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

    args = parser.parse_args()
    sys.argv = build_vl_args(args)
    vl_caller.main()


if __name__ == "__main__":
    main()
