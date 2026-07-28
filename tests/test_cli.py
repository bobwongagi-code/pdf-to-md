from test_support import *

import cli


class CliCompositionTests(unittest.TestCase):
    def test_main_writes_markdown_through_application_boundary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.pdf"
            output_path = Path(temp_dir) / "output.md"
            input_path.write_bytes(b"%PDF-1.4\nplaceholder\n")
            parsed = {
                "ok": True,
                "text": "# Converted\n\nbody",
                "result": None,
                "coverage": {
                    "expected_pages": 1,
                    "returned_pages": 1,
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
            with mock.patch(
                "cli.resolve_api_url",
                return_value=("https://example.com/layout-parsing", "test"),
            ):
                with mock.patch(
                    "cli.resolve_access_token",
                    return_value=("test-token", "test"),
                ):
                    with mock.patch("cli.parse_with_auto_split", return_value=parsed):
                        exit_code = cli.main(
                            [
                                "--file-path",
                                str(input_path),
                                "--markdown-output",
                                str(output_path),
                                "--no-assets",
                                "--no-cache",
                            ]
                        )

            self.assertEqual(exit_code, 0)
            self.assertEqual(
                output_path.read_text(encoding="utf-8"),
                "# Converted\n\nbody\n",
            )
