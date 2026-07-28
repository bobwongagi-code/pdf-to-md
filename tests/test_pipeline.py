from test_support import *

class MergeChunkResultsTests(unittest.TestCase):
    def test_merge_chunk_results_combines_text_and_pages(self):
        first = make_chunk_result("chunk one", "p1")
        second = make_chunk_result("chunk two", "p2")

        merged = vl_caller.merge_chunk_results([first, second])

        self.assertTrue(merged["ok"])
        self.assertEqual(merged["text"], "chunk one\n\nchunk two")
        self.assertEqual(
            [entry["provider_page"] for entry in merged["result"]["merged"]["pages"]],
            [{"page": "p1-0"}, {"page": "p2-0"}],
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

    def test_merge_chunk_results_rejects_raw_page_count_mismatch(self):
        chunk = make_chunk_result("chunk", "p", page_count=1)
        chunk["coverage"]["returned_pages"] = 2

        with self.assertRaises(ValueError):
            vl_caller.merge_chunk_results([chunk])

    def test_merge_chunk_results_rejects_incomplete_coverage_metadata(self):
        chunk = make_chunk_result("chunk", "p")
        chunk["coverage"]["missing_pages"] = [1]

        with self.assertRaises(ValueError):
            vl_caller.merge_chunk_results([chunk])

class AutoSplitTests(unittest.TestCase):
    def test_parse_with_auto_split_merges_large_pdf_chunks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "large.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nlarge\n")

            parse_results = [
                make_chunk_result(
                    f"chunk {index}",
                    f"p{index}",
                    page_count=20 if index < 6 else 14,
                )
                for index in range(1, 7)
            ]

            with mock.patch("pipeline.get_pdf_page_count", return_value=114):
                with mock.patch("pipeline.split_pdf") as split_pdf_mock:
                    with mock.patch(
                        "pipeline.parse_document", side_effect=parse_results
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

            with mock.patch("pipeline.get_pdf_page_count", return_value=114):
                with mock.patch("pipeline.split_pdf"):
                    with mock.patch(
                        "pipeline.parse_document", return_value=failing_result
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
                make_chunk_result("chunk one", "p1", page_count=25),
                make_chunk_result("chunk two", "p2", page_count=10),
            ]

            with mock.patch("pipeline.get_pdf_page_count", return_value=35):
                with mock.patch("pipeline.split_pdf") as split_pdf_mock:
                    with mock.patch(
                        "pipeline.parse_document", side_effect=parse_results
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

            with mock.patch("pipeline.get_pdf_page_count", return_value=35):
                with mock.patch("pipeline.split_pdf"):
                    with mock.patch(
                        "pipeline.parse_document",
                        side_effect=[
                            make_chunk_result("cached chunk", "p1", page_count=20),
                            failing_result,
                        ],
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

            with mock.patch("pipeline.get_pdf_page_count", return_value=35):
                with mock.patch("pipeline.split_pdf") as split_pdf_mock:
                    with mock.patch(
                        "pipeline.parse_document",
                        return_value=make_chunk_result("retried chunk", "p2", page_count=15),
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
