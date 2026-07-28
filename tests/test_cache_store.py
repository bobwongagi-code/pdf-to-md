from test_support import *

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

    def test_build_cache_key_changes_when_endpoint_or_token_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nsample\n")
            args = SimpleNamespace(file_path=str(pdf_path), file_type=FILE_TYPE_PDF, chunk_pages=20)
            options = {
                "model": "PaddleOCR-VL-1.6",
                "useDocUnwarping": False,
                "useDocOrientationClassify": False,
                "visualize": False,
            }

            first = vl_caller.build_cache_key(
                args,
                options,
                api_url="https://one.example.com/layout-parsing",
                token="token-one",
            )
            second = vl_caller.build_cache_key(
                args,
                options,
                api_url="https://two.example.com/layout-parsing",
                token="token-one",
            )
            third = vl_caller.build_cache_key(
                args,
                options,
                api_url="https://one.example.com/layout-parsing",
                token="token-two",
            )

            self.assertNotEqual(first, second)
            self.assertNotEqual(first, third)

    def test_build_chunk_cache_key_changes_when_endpoint_or_token_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nsample\n")
            options = {
                "model": "PaddleOCR-VL-1.6",
                "useDocUnwarping": False,
                "useDocOrientationClassify": False,
                "visualize": False,
            }
            first_namespace = vl_caller.build_cache_namespace(
                "https://one.example.com/layout-parsing",
                "token-one",
            )
            second_namespace = vl_caller.build_cache_namespace(
                "https://two.example.com/layout-parsing",
                "token-one",
            )
            third_namespace = vl_caller.build_cache_namespace(
                "https://one.example.com/layout-parsing",
                "token-two",
            )

            first = vl_caller.build_chunk_cache_key(
                pdf_path, 1, 20, FILE_TYPE_PDF, options, first_namespace
            )
            second = vl_caller.build_chunk_cache_key(
                pdf_path, 1, 20, FILE_TYPE_PDF, options, second_namespace
            )
            third = vl_caller.build_chunk_cache_key(
                pdf_path, 1, 20, FILE_TYPE_PDF, options, third_namespace
            )

            self.assertNotEqual(first, second)
            self.assertNotEqual(first, third)

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

            with mock.patch("cache_store.time.time", return_value=100):
                result, resolved_path = vl_caller.load_cached_result(
                    cache_dir, "expired"
                )

            self.assertIsNone(result)
            self.assertEqual(resolved_path, cache_path)
            self.assertFalse(cache_path.exists())

    def test_save_cached_result_wraps_value_with_expiry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            result = {
                "ok": True,
                "text": "fresh",
                "coverage": {
                    "expected_pages": 1,
                    "returned_pages": 1,
                    "missing_pages": [],
                    "duplicate_pages": [],
                    "partial": False,
                    "complete": True,
                },
            }

            with mock.patch("cache_store.time.time", return_value=100):
                with mock.patch("cache_store.get_cache_ttl_seconds", return_value=30):
                    cache_path = vl_caller.save_cached_result(
                        cache_dir, "entry", result
                    )

            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["expires_at"], 130)
            self.assertEqual(payload["value"]["ok"], True)
            self.assertIsNone(payload["value"]["result"])
            self.assertTrue(payload["value"]["cache_raw_omitted"])

            with mock.patch("cache_store.time.time", return_value=110):
                loaded, _ = vl_caller.load_cached_result(
                    cache_dir, "entry", expected_pages=1
                )
            self.assertEqual(loaded["text"], "fresh")

    def test_load_cached_result_rejects_incomplete_coverage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            cache_path = cache_dir / "entry.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": vl_caller.CACHE_SCHEMA_VERSION,
                        "expires_at": 9999999999,
                        "value": {
                            "ok": True,
                            "text": "partial",
                            "coverage": {
                                "expected_pages": 2,
                                "returned_pages": 1,
                                "complete": False,
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            loaded, _ = vl_caller.load_cached_result(cache_dir, "entry", expected_pages=2)

        self.assertIsNone(loaded)
        self.assertFalse(cache_path.exists())

    def test_load_cached_result_rejects_complete_flag_without_full_coverage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = Path(temp_dir)
            cache_path = cache_dir / "entry.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": vl_caller.CACHE_SCHEMA_VERSION,
                        "expires_at": 9999999999,
                        "value": {
                            "ok": True,
                            "text": "looks complete",
                            "coverage": {
                                "expected_pages": 2,
                                "returned_pages": 2,
                                "complete": True,
                                "partial": False,
                                "missing_pages": [2],
                                "duplicate_pages": [],
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            loaded, _ = vl_caller.load_cached_result(cache_dir, "entry", expected_pages=2)

        self.assertIsNone(loaded)
        self.assertFalse(cache_path.exists())
