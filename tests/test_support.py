import importlib.util
import json
import os
import plistlib
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cache_store
import config
import install_quick_action
import lib
import ocr_client
import optimize_file
import pdf_to_md
import pdf_to_md_batch
import pipeline
import split_pdf
import vl_caller
from lib import FILE_TYPE_PDF
from safe_io import OutputPathError, atomic_write_text, paths_collide


def make_chunk_result(text: str, page_marker: str, page_count: int = 1) -> dict:
    pages = [{"page": f"{page_marker}-{index}"} for index in range(page_count)]
    return {
        "ok": True,
        "text": text,
        "result": {
            "result": {
                "layoutParsingResults": pages,
            }
        },
        "coverage": {
            "expected_pages": page_count,
            "returned_pages": page_count,
            "missing_pages": [],
            "empty_pages": [],
            "duplicate_pages": [],
            "page_ids": [],
            "partial": False,
            "complete": True,
        },
        "assets": {},
        "error": None,
    }
