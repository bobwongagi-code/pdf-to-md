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
import lib
from lib import FILE_TYPE_PDF
import pdf_to_md


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


class ConfigTests(unittest.TestCase):
    def test_get_config_prefers_environment_token_over_keychain(self):
        with mock.patch.dict(
            os.environ,
            {
                "PADDLEOCR_DOC_PARSING_API_URL": "https://example.com/layout-parsing",
                "PADDLEOCR_ACCESS_TOKEN": "env-token",
            },
            clear=True,
        ):
            with mock.patch("lib._get_keychain_secret", return_value="keychain-token"):
                api_url, token, api_source, token_source = lib.get_config_with_sources()

        self.assertEqual(api_url, "https://example.com/layout-parsing")
        self.assertEqual(token, "env-token")
        self.assertEqual(api_source, "environment")
        self.assertEqual(token_source, "environment")

    def test_get_config_uses_keychain_token_when_env_token_missing(self):
        with mock.patch.dict(
            os.environ,
            {"PADDLEOCR_DOC_PARSING_API_URL": "example.com/layout-parsing"},
            clear=True,
        ):
            with mock.patch("lib._get_keychain_secret", return_value="keychain-token"):
                api_url, token, _, token_source = lib.get_config_with_sources()

        self.assertEqual(api_url, "https://example.com/layout-parsing")
        self.assertEqual(token, "keychain-token")
        self.assertEqual(token_source, "keychain:pdf-to-md.paddleocr/PADDLEOCR_ACCESS_TOKEN")

    def test_get_config_errors_when_no_env_or_keychain_token(self):
        with mock.patch.dict(
            os.environ,
            {"PADDLEOCR_DOC_PARSING_API_URL": "https://example.com/layout-parsing"},
            clear=True,
        ):
            with mock.patch("lib._get_keychain_secret", return_value=""):
                with self.assertRaises(ValueError) as ctx:
                    lib.get_config_with_sources()

        self.assertIn("environment or macOS Keychain", str(ctx.exception))

    def test_get_keychain_secret_respects_disable_flag(self):
        with mock.patch.dict(os.environ, {"PADDLEOCR_DISABLE_KEYCHAIN": "1"}, clear=True):
            with mock.patch("lib.subprocess.run") as run_mock:
                token = lib._get_keychain_secret("pdf-to-md.paddleocr", "PADDLEOCR_ACCESS_TOKEN")

        self.assertEqual(token, "")
        run_mock.assert_not_called()


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


class MarkdownOutputTests(unittest.TestCase):
    def test_resolve_markdown_output_path_uses_explicit_path(self):
        resolved = vl_caller.resolve_markdown_output_path(
            "~/custom/output.md",
            "/tmp/input.pdf",
        )
        self.assertEqual(resolved, Path("~/custom/output.md").expanduser().resolve())

    def test_resolve_markdown_output_path_uses_input_basename_for_local_file(self):
        resolved = vl_caller.resolve_markdown_output_path(
            None,
            "/tmp/sample.pdf",
        )
        self.assertEqual(resolved, Path("/tmp/sample.md").resolve())

    def test_extract_markdown_text_returns_top_level_text(self):
        self.assertEqual(
            vl_caller.extract_markdown_text({"text": "# title\n\nbody"}),
            "# title\n\nbody",
        )

    def test_extract_markdown_text_falls_back_to_empty_string(self):
        self.assertEqual(vl_caller.extract_markdown_text({"text": None}), "")

    def test_write_markdown_file_appends_trailing_newline(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "result.md"
            vl_caller.write_markdown_file(output_path, "# heading")
            self.assertEqual(output_path.read_text(encoding="utf-8"), "# heading\n")


class WrapperScriptTests(unittest.TestCase):
    def test_build_vl_args_uses_write_markdown_by_default(self):
        args = SimpleNamespace(
            file_path="~/docs/sample.pdf",
            markdown_output=None,
            output=None,
            file_type=None,
            pretty=False,
            doc_unwarping=False,
            orientation_classify=False,
            timing=False,
            no_cache=False,
            cache_dir=None,
            chunk_pages=None,
            chunk_workers=None,
        )

        vl_args = pdf_to_md.build_vl_args(args)

        self.assertEqual(vl_args[0], "vl_caller.py")
        self.assertIn("--file-path", vl_args)
        self.assertIn("--write-markdown", vl_args)
        self.assertNotIn("--markdown-output", vl_args)

    def test_build_vl_args_preserves_optional_flags(self):
        args = SimpleNamespace(
            file_path="/tmp/sample.pdf",
            markdown_output="/tmp/out.md",
            output="/tmp/out.json",
            file_type=FILE_TYPE_PDF,
            pretty=True,
            doc_unwarping=True,
            orientation_classify=True,
            timing=True,
            no_cache=True,
            cache_dir="/tmp/cache",
            chunk_pages=20,
            chunk_workers=1,
        )

        vl_args = pdf_to_md.build_vl_args(args)

        self.assertIn("--markdown-output", vl_args)
        self.assertIn("/tmp/out.md", vl_args)
        self.assertIn("--output", vl_args)
        self.assertIn("/tmp/out.json", vl_args)
        self.assertIn("--file-type", vl_args)
        self.assertIn(str(FILE_TYPE_PDF), vl_args)
        self.assertIn("--pretty", vl_args)
        self.assertIn("--doc-unwarping", vl_args)
        self.assertIn("--orientation-classify", vl_args)
        self.assertIn("--timing", vl_args)
        self.assertIn("--no-cache", vl_args)
        self.assertIn("--cache-dir", vl_args)
        self.assertIn("--chunk-pages", vl_args)
        self.assertIn("20", vl_args)
        self.assertIn("--chunk-workers", vl_args)


class AutoSplitTests(unittest.TestCase):
    def test_parse_with_auto_split_merges_large_pdf_chunks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "large.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nlarge\n")

            parse_results = [
                make_chunk_result(f"chunk {index}", f"p{index}")
                for index in range(1, 7)
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
            self.assertEqual(
                result["text"],
                "chunk 1\n\nchunk 2\n\nchunk 3\n\nchunk 4\n\nchunk 5\n\nchunk 6",
            )
            self.assertEqual(split_pdf_mock.call_count, 6)
            self.assertEqual(split_pdf_mock.call_args_list[0].args[2], "1-20")
            self.assertEqual(split_pdf_mock.call_args_list[-1].args[2], "101-114")
            self.assertEqual(parse_document_mock.call_count, 6)

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
            self.assertIn("[chunk 1/6, pages 1-20]", result["error"]["message"])
            self.assertIn("timed out", result["error"]["message"])

    def test_parse_with_auto_split_accepts_chunk_page_override(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "large.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nlarge\n")
            parse_results = [
                make_chunk_result("chunk one", "p1"),
                make_chunk_result("chunk two", "p2"),
            ]

            with mock.patch("vl_caller.get_pdf_page_count", return_value=35):
                with mock.patch("vl_caller.split_pdf") as split_pdf_mock:
                    with mock.patch(
                        "vl_caller.parse_document", side_effect=parse_results
                    ):
                        result = vl_caller.parse_with_auto_split(
                            file_path=str(pdf_path),
                            file_type=FILE_TYPE_PDF,
                            api_url="https://example.com/layout-parsing",
                            token="dummy-token",
                            chunk_pages=25,
                            chunk_workers=1,
                        )

            self.assertTrue(result["ok"])
            self.assertEqual(split_pdf_mock.call_count, 2)
            self.assertEqual(split_pdf_mock.call_args_list[0].args[2], "1-25")
            self.assertEqual(split_pdf_mock.call_args_list[1].args[2], "26-35")

    def test_parse_with_auto_split_reuses_successful_chunk_cache_after_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "large.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nlarge\n")
            cache_dir = Path(temp_dir) / "cache"
            failing_result = {
                "ok": False,
                "text": "",
                "result": None,
                "error": {"code": "API_ERROR", "message": "timed out"},
            }

            with mock.patch("vl_caller.get_pdf_page_count", return_value=35):
                with mock.patch("vl_caller.split_pdf"):
                    with mock.patch(
                        "vl_caller.parse_document",
                        side_effect=[make_chunk_result("cached chunk", "p1"), failing_result],
                    ):
                        first_result = vl_caller.parse_with_auto_split(
                            file_path=str(pdf_path),
                            file_type=FILE_TYPE_PDF,
                            api_url="https://example.com/layout-parsing",
                            token="dummy-token",
                            cache_dir=cache_dir,
                            chunk_pages=20,
                            chunk_workers=1,
                        )

            self.assertFalse(first_result["ok"])
            self.assertIn("Rerun the same command with cache enabled", first_result["error"]["message"])

            with mock.patch("vl_caller.get_pdf_page_count", return_value=35):
                with mock.patch("vl_caller.split_pdf") as split_pdf_mock:
                    with mock.patch(
                        "vl_caller.parse_document",
                        return_value=make_chunk_result("retried chunk", "p2"),
                    ) as parse_document_mock:
                        second_result = vl_caller.parse_with_auto_split(
                            file_path=str(pdf_path),
                            file_type=FILE_TYPE_PDF,
                            api_url="https://example.com/layout-parsing",
                            token="dummy-token",
                            cache_dir=cache_dir,
                            chunk_pages=20,
                            chunk_workers=1,
                        )

            self.assertTrue(second_result["ok"])
            self.assertEqual(second_result["text"], "cached chunk\n\nretried chunk")
            self.assertEqual(split_pdf_mock.call_count, 1)
            self.assertEqual(split_pdf_mock.call_args_list[0].args[2], "21-35")
            self.assertEqual(parse_document_mock.call_count, 1)

    def test_validate_markdown_output_rejects_failed_or_empty_results(self):
        ok, message = vl_caller.validate_markdown_output(
            {"ok": False, "text": "", "error": {"message": "timed out"}}
        )
        self.assertFalse(ok)
        self.assertEqual(message, "timed out")

        ok, message = vl_caller.validate_markdown_output(
            {"ok": True, "text": "   ", "error": None}
        )
        self.assertFalse(ok)
        self.assertIn("empty", message)


if __name__ == "__main__":
    unittest.main()
