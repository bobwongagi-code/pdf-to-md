#!/usr/bin/env python3
"""Inspect or explicitly purge pdf-to-md OCR cache files."""

import argparse
from pathlib import Path

from cache_store import get_default_cache_dir


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Inspect or purge pdf-to-md OCR cache")
    parser.add_argument("--cache-dir", metavar="DIR", help="Cache directory to inspect")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Delete all generated cache files",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm deletion when used with --all",
    )
    args = parser.parse_args(argv)
    cache_dir = Path(args.cache_dir).expanduser().resolve() if args.cache_dir else get_default_cache_dir()
    if not cache_dir.exists():
        print(f"Cache directory does not exist: {cache_dir}")
        return 0
    if not args.all:
        files = [path for path in cache_dir.rglob("*.json") if path.is_file()]
        total = sum(path.stat().st_size for path in files)
        print(f"Cache: {cache_dir}")
        print(f"Entries: {len(files)}")
        print(f"Size: {total / 1024 / 1024:.2f} MB")
        print("Use --all --yes to remove generated cache entries.")
        return 0
    if not args.yes:
        parser.error("--all requires --yes")
    removed = 0
    for path in cache_dir.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix not in {".json", ".lock"}:
            continue
        path.unlink()
        removed += 1
    for directory in sorted(
        (path for path in cache_dir.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        try:
            directory.rmdir()
        except OSError:
            pass
    print(f"Removed {removed} cache file(s) from {cache_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
