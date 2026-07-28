from test_support import *

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
            with mock.patch("config._get_keychain_secret", return_value="keychain-token"):
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
            with mock.patch("config._get_keychain_secret", return_value="keychain-token"):
                api_url, token, _, token_source = lib.get_config_with_sources()

        self.assertEqual(api_url, "https://example.com/layout-parsing")
        self.assertEqual(token, "keychain-token")
        self.assertEqual(token_source, "keychain:pdf-to-md.paddleocr/PADDLEOCR_ACCESS_TOKEN")

    def test_get_config_reads_api_url_from_local_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.env"
            config_path.write_text(
                "PADDLEOCR_DOC_PARSING_API_URL=https://example.com/layout-parsing\n",
                encoding="utf-8",
            )
            with mock.patch.dict(
                os.environ,
                {"PDF_TO_MD_CONFIG_FILE": str(config_path)},
                clear=True,
            ):
                with mock.patch("config._get_keychain_secret", return_value="keychain-token"):
                    api_url, _, api_source, _ = lib.get_config_with_sources()

        self.assertEqual(api_url, "https://example.com/layout-parsing")
        self.assertEqual(api_source, "local-config")

    def test_config_rejects_non_https_endpoint_by_default(self):
        with mock.patch.dict(
            os.environ,
            {
                "PADDLEOCR_DOC_PARSING_API_URL": "http://example.com/layout-parsing",
                "PADDLEOCR_ACCESS_TOKEN": "token",
            },
            clear=True,
        ):
            with self.assertRaises(ValueError) as ctx:
                lib.get_config_with_sources()

        self.assertIn("must use HTTPS", str(ctx.exception))

    def test_config_normalizes_endpoint_and_rejects_query_parameters(self):
        endpoint, _ = lib.resolve_api_url("HTTPS://example.com/layout-parsing/")
        self.assertEqual(endpoint, "https://example.com/layout-parsing")

        with self.assertRaises(ValueError):
            lib.resolve_api_url("https://example.com/layout-parsing?token=secret")

    def test_local_file_magic_must_match_explicit_file_type(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "scan.png"
            image_path.write_bytes(b"not an image")
            with mock.patch("ocr_client._make_api_request") as request_mock:
                result = lib.parse_document(
                    file_path=str(image_path),
                    file_type=1,
                    api_url="https://example.com/layout-parsing",
                    token="token",
                )

        self.assertFalse(result["ok"])
        self.assertIn("does not match", result["error"]["message"])
        request_mock.assert_not_called()

    def test_parse_document_preserves_explicit_endpoint_when_token_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "scan.png"
            image_path.write_bytes(b"\x89PNG\r\n\x1a\nsample\n")

            with mock.patch.dict(
                os.environ,
                {
                    "PADDLEOCR_DOC_PARSING_API_URL": "https://configured.example.com/layout-parsing",
                    "PADDLEOCR_ACCESS_TOKEN": "env-token",
                },
                clear=True,
            ):
                with mock.patch("ocr_client._make_api_request") as request_mock:
                    request_mock.return_value = {
                        "errorCode": 0,
                        "result": {
                            "layoutParsingResults": [{"markdown": {"text": "converted"}}]
                        },
                    }
                    lib.parse_document(
                        file_path=str(image_path),
                        api_url="https://explicit.example.com/layout-parsing",
                    )

        self.assertEqual(request_mock.call_args.args[0], "https://explicit.example.com/layout-parsing")

    def test_get_doc_parsing_model_defaults_to_vl_16(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(lib.get_doc_parsing_model(), "PaddleOCR-VL-1.6")

    def test_get_doc_parsing_model_can_be_overridden(self):
        with mock.patch.dict(
            os.environ,
            {"PADDLEOCR_DOC_PARSING_MODEL": "PaddleOCR-VL-1.5"},
            clear=True,
        ):
            self.assertEqual(lib.get_doc_parsing_model(), "PaddleOCR-VL-1.5")

    def test_get_config_errors_when_no_env_or_keychain_token(self):
        with mock.patch.dict(
            os.environ,
            {"PADDLEOCR_DOC_PARSING_API_URL": "https://example.com/layout-parsing"},
            clear=True,
        ):
            with mock.patch("config._get_keychain_secret", return_value=""):
                with self.assertRaises(ValueError) as ctx:
                    lib.get_config_with_sources()

        self.assertIn("environment or macOS Keychain", str(ctx.exception))

    def test_get_keychain_secret_respects_disable_flag(self):
        with mock.patch.dict(os.environ, {"PADDLEOCR_DISABLE_KEYCHAIN": "1"}, clear=True):
            with mock.patch("config.subprocess.run") as run_mock:
                token = lib._get_keychain_secret("pdf-to-md.paddleocr", "PADDLEOCR_ACCESS_TOKEN")

        self.assertEqual(token, "")
        run_mock.assert_not_called()

class ApiRequestTests(unittest.TestCase):
    @staticmethod
    def stream_response(response):
        @contextmanager
        def context():
            yield response

        return context()

    def test_make_api_request_applies_configured_timeout_to_reused_client(self):
        client = mock.Mock()
        response = httpx.Response(
            200,
            json={"errorCode": 0},
            request=httpx.Request("POST", "https://example.com/layout-parsing"),
        )
        client.stream.return_value = self.stream_response(response)

        with mock.patch.dict(
            os.environ,
            {
                "PADDLEOCR_DOC_PARSING_TIMEOUT": "120",
                "PADDLEOCR_DOC_PARSING_CONNECT_TIMEOUT": "7",
                "PADDLEOCR_DOC_PARSING_MAX_RETRIES": "0",
            },
            clear=True,
        ):
            lib._make_api_request(
                "https://example.com/layout-parsing",
                "token",
                {"file": "payload"},
                client=client,
            )

        timeout = client.stream.call_args.kwargs["timeout"]
        self.assertEqual(timeout.read, 120)
        self.assertEqual(timeout.connect, 7)
        self.assertIn("Idempotency-Key", client.stream.call_args.kwargs["headers"])

    def test_make_api_request_uses_retry_after_for_429(self):
        client = mock.Mock()
        response_429 = httpx.Response(
            429,
            headers={"Retry-After": "2"},
            json={"errorMsg": "slow down"},
            request=httpx.Request("POST", "https://example.com/layout-parsing"),
        )
        response_200 = httpx.Response(
            200,
            json={"errorCode": 0},
            request=httpx.Request("POST", "https://example.com/layout-parsing"),
        )
        client.stream.side_effect = [
            self.stream_response(response_429),
            self.stream_response(response_200),
        ]

        with mock.patch.dict(
            os.environ,
            {"PADDLEOCR_DOC_PARSING_MAX_RETRIES": "1"},
            clear=True,
        ):
            with mock.patch("ocr_client.time.sleep") as sleep_mock:
                lib._make_api_request(
                    "https://example.com/layout-parsing",
                    "token",
                    {"file": "payload"},
                    client=client,
                )

        sleep_mock.assert_called_once_with(2.0)

    def test_make_api_request_rejects_oversized_streamed_response(self):
        client = mock.Mock()
        response = httpx.Response(
            200,
            content=b"x" * (1024 * 1024 + 1),
            request=httpx.Request("POST", "https://example.com/layout-parsing"),
        )
        client.stream.return_value = self.stream_response(response)

        with mock.patch.dict(
            os.environ,
            {
                "PADDLEOCR_DOC_PARSING_MAX_RESPONSE_MB": "1",
                "PADDLEOCR_DOC_PARSING_MAX_RETRIES": "0",
            },
            clear=True,
        ):
            with self.assertRaises(RuntimeError) as ctx:
                lib._make_api_request(
                    "https://example.com/layout-parsing",
                    "token",
                    {"file": "payload"},
                    client=client,
                )

        self.assertIn("response", str(ctx.exception))

    def test_make_api_request_redacts_token_from_provider_error(self):
        client = mock.Mock()
        sentinel = "secret-token"
        response = httpx.Response(
            500,
            json={"errorMsg": f"provider echoed {sentinel}"},
            request=httpx.Request("POST", "https://example.com/layout-parsing"),
        )
        client.stream.return_value = self.stream_response(response)

        with mock.patch.dict(
            os.environ,
            {"PADDLEOCR_DOC_PARSING_MAX_RETRIES": "0"},
            clear=True,
        ):
            with self.assertRaises(RuntimeError) as ctx:
                lib._make_api_request(
                    "https://example.com/layout-parsing",
                    sentinel,
                    {"file": "payload"},
                    client=client,
                )

        self.assertNotIn(sentinel, str(ctx.exception))

    def test_make_api_request_enforces_request_size_limit(self):
        with mock.patch.dict(
            os.environ,
            {
                "PADDLEOCR_DOC_PARSING_MAX_REQUEST_MB": "1",
            },
            clear=True,
        ):
            with self.assertRaises(RuntimeError) as ctx:
                lib._make_api_request(
                    "https://example.com/layout-parsing",
                    "token",
                    {"file": "x" * (1024 * 1024)},
                    client=mock.Mock(),
                )

        self.assertIn("request", str(ctx.exception))

    def test_parse_document_sends_default_vl_16_model(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "scan.png"
            image_path.write_bytes(b"\x89PNG\r\n\x1a\nsample\n")

            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("ocr_client._make_api_request") as request_mock:
                    request_mock.return_value = {
                        "errorCode": 0,
                        "result": {
                            "layoutParsingResults": [
                                {"markdown": {"text": "converted"}}
                            ]
                        },
                    }
                    result = lib.parse_document(
                        file_path=str(image_path),
                        api_url="https://example.com/layout-parsing",
                        token="token",
                    )

        self.assertTrue(result["ok"])
        params = request_mock.call_args.args[2]
        self.assertEqual(params["model"], "PaddleOCR-VL-1.6")

    def test_parse_document_allows_explicit_model_override(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "scan.png"
            image_path.write_bytes(b"\x89PNG\r\n\x1a\nsample\n")

            with mock.patch("ocr_client._make_api_request") as request_mock:
                request_mock.return_value = {
                    "errorCode": 0,
                    "result": {
                        "layoutParsingResults": [
                            {"markdown": {"text": "converted"}}
                        ]
                    },
                }
                result = lib.parse_document(
                    file_path=str(image_path),
                    api_url="https://example.com/layout-parsing",
                    token="token",
                    model="PaddleOCR-VL-1.5",
                )

        self.assertTrue(result["ok"])
        params = request_mock.call_args.args[2]
        self.assertEqual(params["model"], "PaddleOCR-VL-1.5")

    def test_parse_document_rejects_empty_page_list(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "scan.png"
            image_path.write_bytes(b"\x89PNG\r\n\x1a\nsample\n")

            with mock.patch("ocr_client._make_api_request") as request_mock:
                request_mock.return_value = {
                    "errorCode": 0,
                    "result": {"layoutParsingResults": []},
                }
                result = lib.parse_document(
                    file_path=str(image_path),
                    api_url="https://example.com/layout-parsing",
                    token="token",
                )

        self.assertFalse(result["ok"])
        self.assertIn("empty", result["error"]["message"])

    def test_parse_document_rejects_partial_expected_pages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "scan.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nsample\n")

            with mock.patch("ocr_client._make_api_request") as request_mock:
                request_mock.return_value = {
                    "errorCode": 0,
                    "result": {
                        "layoutParsingResults": [{"markdown": {"text": "page one"}}]
                    },
                }
                result = lib.parse_document(
                    file_path=str(pdf_path),
                    api_url="https://example.com/layout-parsing",
                    token="token",
                    expected_pages=2,
                )

        self.assertFalse(result["ok"])
        self.assertIn("expected 2", result["error"]["message"])

    def test_parse_document_rejects_unmarked_empty_page(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "scan.png"
            image_path.write_bytes(b"\x89PNG\r\n\x1a\nsample\n")
            with mock.patch("ocr_client._make_api_request", return_value={
                "errorCode": 0,
                "result": {
                    "layoutParsingResults": [
                        {"markdown": {"text": ""}},
                    ]
                },
            }):
                result = lib.parse_document(
                    file_path=str(image_path),
                    api_url="https://example.com/layout-parsing",
                    token="token",
                )

        self.assertFalse(result["ok"])
        self.assertIn("explicit blank-page", result["error"]["message"])

    def test_parse_document_preserves_explicit_blank_page_as_markdown_comment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "blank.png"
            image_path.write_bytes(b"\x89PNG\r\n\x1a\nsample\n")
            with mock.patch("ocr_client._make_api_request", return_value={
                "errorCode": 0,
                "result": {
                    "layoutParsingResults": [
                        {"isBlank": True, "markdown": {"text": ""}},
                    ]
                },
            }):
                result = lib.parse_document(
                    file_path=str(image_path),
                    api_url="https://example.com/layout-parsing",
                    token="token",
                )

        self.assertTrue(result["ok"])
        self.assertIn("blank page", result["text"])

    def test_parse_document_rejects_out_of_order_page_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "scan.png"
            image_path.write_bytes(b"\x89PNG\r\n\x1a\nsample\n")
            with mock.patch("ocr_client._make_api_request", return_value={
                "errorCode": 0,
                "result": {
                    "layoutParsingResults": [
                        {"pageIndex": 1, "markdown": {"text": "two"}},
                        {"pageIndex": 0, "markdown": {"text": "one"}},
                    ]
                },
            }):
                result = lib.parse_document(
                    file_path=str(image_path),
                    api_url="https://example.com/layout-parsing",
                    token="token",
                )

        self.assertFalse(result["ok"])
        self.assertIn("out of order", result["error"]["message"])

    def test_parse_document_rejects_duplicate_page_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "scan.png"
            image_path.write_bytes(b"\x89PNG\r\n\x1a\nsample\n")
            with mock.patch("ocr_client._make_api_request", return_value={
                "errorCode": 0,
                "result": {
                    "layoutParsingResults": [
                        {"pageIndex": 0, "markdown": {"text": "one"}},
                        {"pageIndex": 0, "markdown": {"text": "two"}},
                    ]
                },
            }):
                result = lib.parse_document(
                    file_path=str(image_path),
                    api_url="https://example.com/layout-parsing",
                    token="token",
                )

        self.assertFalse(result["ok"])
        self.assertIn("duplicate page", result["error"]["message"])
