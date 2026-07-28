from test_support import *

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
        self.assertEqual(resolved, Path("/tmp/sample.pdf.md").resolve())

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

    def test_write_markdown_file_rejects_existing_output_without_force(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "result.md"
            output_path.write_text("existing\n", encoding="utf-8")

            with self.assertRaises(OutputPathError):
                vl_caller.write_markdown_file(output_path, "# heading")

            self.assertEqual(output_path.read_text(encoding="utf-8"), "existing\n")

    def test_materialize_markdown_assets_writes_local_sibling_resource(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            markdown_path = Path(temp_dir) / "document.pdf.md"
            result = {
                "text": "![figure](imgs/figure.png)",
                "assets": {
                    "imgs/figure.png": "data:image/png;base64,iVBORw0KGgo=",
                },
            }

            text = vl_caller.materialize_markdown_assets(result, markdown_path)

            asset_dir = Path(temp_dir) / "document.pdf.assets"
            self.assertTrue(asset_dir.is_dir())
            self.assertNotIn("imgs/figure.png", text)
            self.assertIn("document.pdf.assets/", text)
            self.assertEqual(len(list(asset_dir.iterdir())), 1)

    def test_materialize_markdown_assets_does_not_replace_arbitrary_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            markdown_path = Path(temp_dir) / "document.pdf.md"
            result = {
                "text": "A catalog entry: a. Image: ![figure](a)",
                "assets": {
                    "a": "data:image/png;base64,iVBORw0KGgo=",
                },
            }

            text = vl_caller.materialize_markdown_assets(result, markdown_path)

            self.assertIn("catalog entry: a", text)
            self.assertEqual(text.count("document.pdf.assets/"), 1)

    def test_materialize_markdown_assets_replaces_stale_assets_on_force(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            markdown_path = Path(temp_dir) / "document.pdf.md"
            asset_dir = Path(temp_dir) / "document.pdf.assets"
            asset_dir.mkdir()
            (asset_dir / "stale.txt").write_text("stale", encoding="utf-8")
            result = {
                "text": "![figure](imgs/figure.png)",
                "assets": {
                    "imgs/figure.png": "data:image/png;base64,iVBORw0KGgo=",
                },
            }

            vl_caller.materialize_markdown_assets(
                result,
                markdown_path,
                force=True,
            )

            self.assertFalse((asset_dir / "stale.txt").exists())

    def test_materialize_markdown_assets_deduplicates_same_source_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            markdown_path = Path(temp_dir) / "document.pdf.md"
            result = {
                "text": "![one](one.png)\n![two](two.png)",
                "assets": {
                    "one.png": "data:image/png;base64,iVBORw0KGgo=",
                    "two.png": "data:image/png;base64,iVBORw0KGgo=",
                },
            }

            text = vl_caller.materialize_markdown_assets(result, markdown_path)

            self.assertEqual(len(list((Path(temp_dir) / "document.pdf.assets").iterdir())), 1)
            self.assertEqual(text.count("document.pdf.assets/"), 2)

    def test_materialize_markdown_assets_enforces_total_asset_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            markdown_path = Path(temp_dir) / "document.pdf.md"
            result = {
                "text": "![one](one.png)\n![two](two.png)",
                "assets": {
                    "one.png": "data:image/png;base64,iVBORw0KGgo=",
                    "two.png": "data:image/png;base64,AA==",
                },
            }
            with mock.patch.dict(
                os.environ,
                {"PADDLEOCR_DOC_PARSING_MAX_ASSET_COUNT": "1"},
                clear=False,
            ):
                with self.assertRaises(ValueError):
                    vl_caller.materialize_markdown_assets(result, markdown_path)
