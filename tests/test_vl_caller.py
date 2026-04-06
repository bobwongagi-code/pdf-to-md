import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import vl_caller
from lib import FILE_TYPE_PDF


def make_chunk_result(text: str, page_marker: str) -> dict:
    return {
        "ok": True,
        "text": text,
        "result": {
            "result": {
                "layoutParsingResults": [{"page": page_marker}],
            }
        },
        "error": None,
    }


class CacheKeyTests(unittest.TestCase):
    def test_build_cache_key_uses_effective_file_type_for_pdf(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nsample\n")
            options = {
                "useDocUnwarping": False,
                "useDocOrientationClassify": False,
                "visualize": False,
            }

            inferred_args = SimpleNamespace(file_path=str(pdf_path), file_type=None)
            explicit_args = SimpleNamespace(
                file_path=str(pdf_path), file_type=FILE_TYPE_PDF
            )

            inferred_key = vl_caller.build_cache_key(inferred_args, options)
            explicit_key = vl_caller.build_cache_key(explicit_args, options)

            self.assertEqual(inferred_key, explicit_key)

    def test_build_cache_key_changes_when_runtime_options_change(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nsample\n")
            args = SimpleNamespace(file_path=str(pdf_path), file_type=FILE_TYPE_PDF)

            default_options = {
                "useDocUnwarping": False,
                "useDocOrientationClassify": False,
                "visualize": False,
            }
            unwarped_options = {
                "useDocUnwarping": True,
                "useDocOrientationClassify": False,
                "visualize": False,
            }

            default_key = vl_caller.build_cache_key(args, default_options)
            unwarped_key = vl_caller.build_cache_key(args, unwarped_options)

            self.assertNotEqual(default_key, unwarped_key)


class CacheTtlTests(unittest.TestCase):
    def test_load_cached_result_drops_expired_entry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            cache_path = cache_dir / "expired.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "expires_at": 1,
                        "value": {"ok": True, "text": "stale"},
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch("vl_caller.time.time", return_value=100):
                result, resolved_path = vl_caller.load_cached_result(
                    cache_dir, "expired"
                )

            self.assertIsNone(result)
            self.assertEqual(resolved_path, cache_path)
            self.assertFalse(cache_path.exists())

    def test_save_cached_result_wraps_value_with_expiry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            result = {"ok": True, "text": "fresh"}

            with mock.patch("vl_caller.time.time", return_value=100):
                with mock.patch("vl_caller.get_cache_ttl_seconds", return_value=30):
                    cache_path = vl_caller.save_cached_result(
                        cache_dir, "entry", result
                    )

            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["expires_at"], 130)
            self.assertEqual(payload["value"], result)


class MergeChunkResultsTests(unittest.TestCase):
    def test_merge_chunk_results_combines_text_and_pages(self):
        first = make_chunk_result("chunk one", "p1")
        second = make_chunk_result("chunk two", "p2")

        merged = vl_caller.merge_chunk_results([first, second])

        self.assertTrue(merged["ok"])
        self.assertEqual(merged["text"], "chunk one\n\nchunk two")
        self.assertEqual(
            merged["result"]["result"]["layoutParsingResults"],
            [{"page": "p1"}, {"page": "p2"}],
        )

    def test_merge_chunk_results_returns_first_error_chunk(self):
        error_chunk = {
            "ok": False,
            "text": "",
            "result": None,
            "error": {"code": "API_ERROR", "message": "boom"},
        }

        merged = vl_caller.merge_chunk_results([error_chunk])

        self.assertIs(merged, error_chunk)


class AutoSplitTests(unittest.TestCase):
    def test_parse_with_auto_split_merges_large_pdf_chunks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "large.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nlarge\n")

            parse_results = [
                make_chunk_result("chunk one", "p1"),
                make_chunk_result("chunk two", "p2"),
            ]

            with mock.patch("vl_caller.get_pdf_page_count", return_value=114):
                with mock.patch("vl_caller.split_pdf") as split_pdf_mock:
                    with mock.patch(
                        "vl_caller.parse_document", side_effect=parse_results
                    ) as parse_document_mock:
                        with mock.patch.dict(
                            os.environ,
                            {"PADDLEOCR_DOC_PARSING_MAX_CHUNK_WORKERS": "1"},
                            clear=False,
                        ):
                            result = vl_caller.parse_with_auto_split(
                                file_path=str(pdf_path),
                                file_type=FILE_TYPE_PDF,
                                api_url="https://example.com/layout-parsing",
                                token="dummy-token",
                            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["text"], "chunk one\n\nchunk two")
            self.assertEqual(split_pdf_mock.call_count, 2)
            self.assertEqual(split_pdf_mock.call_args_list[0].args[2], "1-100")
            self.assertEqual(split_pdf_mock.call_args_list[1].args[2], "101-114")
            self.assertEqual(parse_document_mock.call_count, 2)

    def test_parse_with_auto_split_prefixes_chunk_error_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "large.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nlarge\n")

            failing_result = {
                "ok": False,
                "text": "",
                "result": None,
                "error": {"code": "API_ERROR", "message": "timed out"},
            }

            with mock.patch("vl_caller.get_pdf_page_count", return_value=114):
                with mock.patch("vl_caller.split_pdf"):
                    with mock.patch(
                        "vl_caller.parse_document", return_value=failing_result
                    ):
                        with mock.patch.dict(
                            os.environ,
                            {"PADDLEOCR_DOC_PARSING_MAX_CHUNK_WORKERS": "1"},
                            clear=False,
                        ):
                            result = vl_caller.parse_with_auto_split(
                                file_path=str(pdf_path),
                                file_type=FILE_TYPE_PDF,
                                api_url="https://example.com/layout-parsing",
                                token="dummy-token",
                            )

            self.assertFalse(result["ok"])
            self.assertIn("[chunk 1/2, pages 1-100]", result["error"]["message"])
            self.assertIn("timed out", result["error"]["message"])


if __name__ == "__main__":
    unittest.main()
