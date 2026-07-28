from test_support import *

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
            force=False,
            keep_raw=False,
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
            force=True,
            keep_raw=True,
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
        self.assertIn("--force", vl_args)
        self.assertIn("--keep-raw", vl_args)

    def test_wrapper_passes_asset_output_without_mutating_process_arguments(self):
        args = SimpleNamespace(
            file_path="/tmp/sample.pdf",
            markdown_output="/tmp/out.md",
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
            force=False,
            allow_insecure_http=False,
            no_assets=False,
            assets_output="/tmp/out.assets",
            assets_reference_name="out.assets",
        )
        self.assertIn("--assets-output", pdf_to_md.build_vl_args(args))
        original_argv = list(sys.argv)
        with mock.patch.object(vl_caller, "main", return_value=0) as main_mock:
            result = pdf_to_md.main(["/tmp/sample.pdf", "--markdown-output", "/tmp/out.md"])

        self.assertEqual(result, 0)
        self.assertEqual(sys.argv, original_argv)
        self.assertIn("--write-markdown", main_mock.call_args.args[0])
