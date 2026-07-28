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

"""Command-line orchestration for the PDF-to-Markdown converter."""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

from artifacts import (
    extract_markdown_text,
    materialize_markdown_assets,
    resolve_assets_output_path,
    resolve_markdown_output_path,
    resolve_output_path,
    validate_markdown_output,
    write_json_file,
    write_markdown_file,
)
from cache_store import (
    build_cache_key,
    cache_entry_lock,
    load_cached_result,
    resolve_cache_dir,
    save_cached_result,
)
from config import (
    DEFAULT_MAX_CHUNK_WORKERS,
    DEFAULT_MAX_PAGES_PER_REQUEST,
    get_doc_parsing_model,
    get_task_timeout_seconds,
    metric_add,
    resolve_access_token,
    resolve_api_url,
)
from contracts import ParseResult
from ocr_client import parse_document
from pipeline import merge_metrics, parse_with_auto_split
from safe_io import OutputPathError, reject_collisions
from version import VERSION

__version__ = VERSION


def timing_enabled(args: argparse.Namespace) -> bool:
    if getattr(args, "timing", False):
        return True
    return os.getenv("PADDLEOCR_DOC_PARSING_TIMING", "").strip() in {
        "1",
        "true",
        "TRUE",
        "yes",
        "YES",
    }


def print_timing_summary(metrics: Optional[dict[str, float]]) -> None:
    if not metrics:
        return
    print("Timing summary:", file=sys.stderr)
    for key in sorted(metrics):
        value = metrics[key]
        if key.endswith("_count") or key.endswith("_hits") or key.endswith(
            "_misses"
        ):
            print(f"  {key}: {int(value)}", file=sys.stderr)
        else:
            print(f"  {key}: {value:.3f}s", file=sys.stderr)


def print_cli_error(
    message: str,
    *,
    as_json: bool = False,
    code: str = "INPUT_ERROR",
) -> None:
    envelope = {
        "ok": False,
        "text": "",
        "result": None,
        "error": {"code": code, "message": message},
    }
    if as_json:
        print(json.dumps(envelope, ensure_ascii=False))
    else:
        print(f"Error: {message}", file=sys.stderr)


def _parse_main_input(
    args: argparse.Namespace,
    api_url: Optional[str],
    token: Optional[str],
    cache_dir: Path,
    cache_key: Optional[str],
    metrics: Optional[dict[str, float]],
    parse_options: dict,
) -> ParseResult:
    deadline = time.monotonic() + get_task_timeout_seconds()
    if args.file_path:
        return parse_with_auto_split(
            file_path=args.file_path,
            file_type=args.file_type,
            cache_dir=cache_dir if cache_key else None,
            use_cache=bool(cache_key),
            api_url=api_url,
            token=token,
            metrics=metrics,
            chunk_pages=args.chunk_pages,
            chunk_workers=args.chunk_workers,
            deadline=deadline,
            allow_insecure_http=args.allow_insecure_http,
            **parse_options,
        )
    return parse_document(
        file_url=args.file_url,
        file_type=args.file_type,
        api_url=api_url,
        token=token,
        metrics=metrics,
        deadline=deadline,
        allow_insecure_http=args.allow_insecure_http,
        **parse_options,
    )


def _main_impl(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="PaddleOCR Document Parsing - with layout analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Parse document from URL (prints the JSON envelope unless --stdout is used)
  python scripts/vl_caller.py --file-url "https://example.com/document.pdf"

  # Parse local file and print the JSON envelope
  python scripts/vl_caller.py --file-path "./invoice.pdf"

  # Save result to a custom file path
  python scripts/vl_caller.py --file-url "URL" --output "./result.json" --pretty

  # Print JSON to stdout without saving a file
  python scripts/vl_caller.py --file-url "URL" --stdout --pretty
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

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--file-url",
        help="URL to document (PDF, PNG, JPG, etc.)",
    )
    input_group.add_argument(
        "--file-path",
        help="Local file path",
    )
    parser.add_argument(
        "--file-type",
        type=int,
        choices=[0, 1],
        help="Optional file type override (0=PDF, 1=Image)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output",
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
        help="Save the raw provider result to an explicit JSON file",
    )
    output_group.add_argument(
        "--stdout",
        action="store_true",
        help="Print JSON to stdout instead of saving to a file",
    )
    parser.add_argument(
        "--markdown-output",
        metavar="FILE",
        help="Also write extracted Markdown text to this file",
    )
    parser.add_argument(
        "--write-markdown",
        action="store_true",
        help=(
            "Also write extracted Markdown beside a local input file using "
            "the same base name"
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing output files. Inputs are never overwritten.",
    )
    parser.add_argument(
        "--keep-raw",
        action="store_true",
        help="Keep the raw provider JSON and disable cache reuse for this run",
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
        "--allow-insecure-http",
        action="store_true",
        help="Allow HTTP only for loopback development endpoints",
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
    parser.add_argument(
        "--chunk-pages",
        type=int,
        metavar="N",
        help=(
            "Pages per local PDF OCR chunk. Defaults to "
            f"{DEFAULT_MAX_PAGES_PER_REQUEST} for stability."
        ),
    )
    parser.add_argument(
        "--chunk-workers",
        type=int,
        metavar="N",
        help=(
            "Concurrent local PDF OCR chunks. Defaults to "
            f"{DEFAULT_MAX_CHUNK_WORKERS} to avoid API overload."
        ),
    )

    args = parser.parse_args(argv)
    total_started_at = time.perf_counter()
    cache_dir = resolve_cache_dir(args.cache_dir)
    parse_options = {
        "model": get_doc_parsing_model(),
        "useDocUnwarping": bool(args.doc_unwarping),
        "useDocOrientationClassify": bool(args.orientation_classify),
        "visualize": False,
    }
    metrics: Optional[dict[str, float]] = (
        {} if timing_enabled(args) else None
    )
    api_url = None
    token = None
    config_started_at = time.perf_counter()
    try:
        api_url, _ = resolve_api_url(
            allow_insecure_http=args.allow_insecure_http
        )
        token, _ = resolve_access_token()
    except ValueError:
        # The application service will return a structured CONFIG_ERROR.
        pass
    finally:
        metric_add(
            metrics,
            "config_lookup_seconds",
            time.perf_counter() - config_started_at,
        )

    if args.file_path:
        input_path = Path(args.file_path).expanduser()
        if input_path.is_symlink() and os.getenv(
            "PADDLEOCR_ALLOW_SYMLINKS",
            "",
        ).lower() not in {"1", "true", "yes"}:
            print_cli_error(
                "symbolic-link inputs are disabled by default",
                as_json=args.stdout,
            )
            return 2
        if not input_path.exists():
            print_cli_error(
                f"File not found: {input_path}",
                as_json=args.stdout,
            )
            return 2
        if not input_path.is_file():
            print_cli_error(
                f"Not a file: {input_path}",
                as_json=args.stdout,
            )
            return 2
        input_path = input_path.resolve()
    else:
        input_path = None

    save_raw = bool(args.output or args.keep_raw)
    output_path = (
        resolve_output_path(args.output)
        if save_raw and not args.stdout
        else None
    )
    markdown_path = None
    if args.markdown_output or args.write_markdown:
        if args.write_markdown and not args.file_path:
            print(
                "Error: --write-markdown requires --file-path",
                file=sys.stderr,
            )
            return 2
        markdown_path = resolve_markdown_output_path(
            args.markdown_output,
            args.file_path if args.write_markdown else None,
        )
    if args.assets_output and markdown_path is None:
        print_cli_error(
            "--assets-output requires Markdown output",
            as_json=args.stdout,
        )
        return 2
    assets_path = None
    if markdown_path is not None and not args.no_assets:
        assets_path = resolve_assets_output_path(
            args.assets_output,
            markdown_path,
        )
        if args.assets_reference_name:
            reference_name = Path(args.assets_reference_name)
            if (
                reference_name.name != args.assets_reference_name
                or args.assets_reference_name in {"", ".", ".."}
            ):
                print_cli_error(
                    "--assets-reference-name must be a single directory name",
                    as_json=args.stdout,
                )
                return 2

    protected_paths = [input_path] if input_path is not None else []
    try:
        if output_path is not None:
            reject_collisions(
                output_path,
                protected_paths,
                force=args.force,
                label="JSON output",
            )
        if markdown_path is not None:
            reject_collisions(
                markdown_path,
                protected_paths,
                force=args.force,
                label="Markdown output",
            )
        if assets_path is not None:
            reject_collisions(
                assets_path,
                protected_paths
                + ([markdown_path] if markdown_path is not None else []),
                force=args.force,
                label="Markdown asset directory",
            )
        if output_path is not None and markdown_path is not None:
            reject_collisions(
                output_path,
                [markdown_path],
                force=True,
                label="JSON output",
                protected_label="Markdown output",
            )
    except OutputPathError as exc:
        print_cli_error(
            str(exc),
            as_json=args.stdout,
            code="OUTPUT_ERROR",
        )
        return 2

    result = None
    cache_key = None
    cache_path = None
    cache_enabled = not args.no_cache and not args.keep_raw and not args.output
    if cache_enabled:
        try:
            cache_key = build_cache_key(
                args,
                parse_options,
                api_url=api_url,
                token=token,
            )
        except (OSError, ValueError) as exc:
            print_cli_error(
                f"Cannot snapshot local input safely: {exc}",
                as_json=args.stdout,
                code="INPUT_ERROR",
            )
            return 2
        if cache_key:
            with cache_entry_lock(cache_dir, cache_key):
                cache_lookup_started_at = time.perf_counter()
                result, cache_path = load_cached_result(
                    cache_dir,
                    cache_key,
                )
                metric_add(
                    metrics,
                    "full_cache_lookup_seconds",
                    time.perf_counter() - cache_lookup_started_at,
                )
                if result is not None:
                    metric_add(metrics, "full_cache_hits", 1.0)
                else:
                    metric_add(metrics, "full_cache_misses", 1.0)
                if result is None:
                    result = _parse_main_input(
                        args,
                        api_url,
                        token,
                        cache_dir,
                        cache_key,
                        metrics,
                        parse_options,
                    )
                    if result.get("ok"):
                        save_cached_result(
                            cache_dir,
                            cache_key,
                            result,
                            lock_held=True,
                        )
                else:
                    print(
                        f"Using cached result: {cache_path}",
                        file=sys.stderr,
                    )
        else:
            result = _parse_main_input(
                args,
                api_url,
                token,
                cache_dir,
                None,
                metrics,
                parse_options,
            )
    else:
        result = _parse_main_input(
            args,
            api_url,
            token,
            cache_dir,
            None,
            metrics,
            parse_options,
        )

    indent = 2 if args.pretty else None
    markdown_error_code = None
    if markdown_path is not None:
        markdown_write_started_at = time.perf_counter()
        markdown_ok, markdown_error = validate_markdown_output(result)
        if not markdown_ok:
            print(
                f"Error: Markdown not written to {markdown_path}: "
                f"{markdown_error}",
                file=sys.stderr,
            )
            metric_add(
                metrics,
                "markdown_write_seconds",
                time.perf_counter() - markdown_write_started_at,
            )
            if timing_enabled(args):
                metric_add(
                    metrics,
                    "total_seconds",
                    time.perf_counter() - total_started_at,
                )
                print_timing_summary(metrics)
            markdown_error_code = 1
        try:
            if markdown_error_code is None:
                markdown_text = (
                    extract_markdown_text(result)
                    if args.no_assets
                    else materialize_markdown_assets(
                        result,
                        markdown_path,
                        force=args.force,
                        asset_dir=assets_path,
                        asset_reference_name=args.assets_reference_name,
                    )
                )
                write_markdown_file(
                    markdown_path,
                    markdown_text,
                    force=args.force,
                )
                print(
                    f"Markdown saved to: {markdown_path}",
                    file=sys.stderr,
                )
        except (
            PermissionError,
            OSError,
            RuntimeError,
            ValueError,
            OutputPathError,
        ) as exc:
            print(
                f"Error: Cannot write Markdown to {markdown_path}: {exc}",
                file=sys.stderr,
            )
            markdown_error_code = 6
        finally:
            metric_add(
                metrics,
                "markdown_write_seconds",
                time.perf_counter() - markdown_write_started_at,
            )

    if args.stdout or (not save_raw and markdown_path is None):
        print(json.dumps(result, indent=indent, ensure_ascii=False))

    if save_raw and not args.stdout:
        output_write_started_at = time.perf_counter()
        try:
            write_json_file(
                output_path,
                result,
                indent,
                force=args.force,
            )
            print(
                f"Result saved to: {output_path}",
                file=sys.stderr,
            )
        except (PermissionError, OSError, OutputPathError) as exc:
            print(
                f"Warning: raw JSON was not saved to {output_path}: {exc}",
                file=sys.stderr,
            )
            raw_output_failed = True
        else:
            raw_output_failed = False
        finally:
            metric_add(
                metrics,
                "output_write_seconds",
                time.perf_counter() - output_write_started_at,
            )
    else:
        raw_output_failed = False

    metric_add(
        metrics,
        "total_seconds",
        time.perf_counter() - total_started_at,
    )
    if timing_enabled(args):
        print_timing_summary(metrics)
    if markdown_error_code is not None:
        return markdown_error_code
    if raw_output_failed:
        return 5
    return 0 if result["ok"] else 1


def main(argv: Optional[list[str]] = None) -> int:
    """Run the CLI without exposing tracebacks to Finder or agent callers."""
    try:
        return _main_impl(argv)
    except KeyboardInterrupt:
        as_json = "--stdout" in (
            argv if argv is not None else sys.argv[1:]
        )
        print_cli_error(
            "conversion cancelled",
            as_json=as_json,
            code="CANCELLED",
        )
        return 130
    except Exception as exc:
        as_json = "--stdout" in (
            argv if argv is not None else sys.argv[1:]
        )
        print_cli_error(
            f"{type(exc).__name__}: {str(exc)[:500]}",
            as_json=as_json,
            code="INTERNAL_ERROR",
        )
        return 1
