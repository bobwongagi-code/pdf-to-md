#!/usr/bin/env python3
"""Verify the repository's version metadata has one consistent value."""

import json
import re
import sys
from pathlib import Path

from version import VERSION


ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    metadata = json.loads((ROOT / "_meta.json").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(r"version-(\d+\.\d+\.\d+)-blue", readme)
    values = {
        "scripts/version.py": VERSION,
        "_meta.json": metadata.get("version"),
        "README.md": match.group(1) if match else None,
    }
    if any(value != VERSION for value in values.values()):
        for name, value in values.items():
            print(f"{name}: {value!r}", file=sys.stderr)
        return 1
    print(f"Version metadata is consistent: {VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
