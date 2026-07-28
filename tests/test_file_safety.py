from test_support import *

class FileSafetyTests(unittest.TestCase):
    def test_paths_collide_on_case_insensitive_desktop_paths(self):
        if sys.platform != "darwin":
            self.skipTest("case-insensitive path semantics are desktop-specific")
        self.assertTrue(paths_collide(Path("/tmp/Report.md"), Path("/tmp/report.md")))

    def test_split_pdf_rejects_input_output_collision(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "same.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nsample\n")

            with self.assertRaises(OutputPathError):
                split_pdf.split_pdf(pdf_path, pdf_path, "1")

    def test_paths_collide_for_hardlinks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.pdf"
            hardlink = Path(temp_dir) / "alias.pdf"
            source.write_bytes(b"%PDF-1.4\nsample\n")
            os.link(source, hardlink)
            self.assertTrue(paths_collide(source, hardlink))

    def test_atomic_write_does_not_follow_dangling_output_symlink(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "output.md"
            target = Path(temp_dir) / "missing.md"
            output.symlink_to(target)

            with self.assertRaises(OutputPathError):
                atomic_write_text(output, "new")
            atomic_write_text(output, "new", force=True)

            self.assertFalse(output.is_symlink())
            self.assertEqual(output.read_text(encoding="utf-8"), "new")
            self.assertFalse(target.exists())

    def test_install_bundle_rolls_back_all_published_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_runtime = root / "runtime"
            old_runtime.mkdir()
            (old_runtime / "version.py").write_text("old", encoding="utf-8")
            old_workflow = root / "workflow.workflow"
            old_workflow.mkdir()
            (old_workflow / "document.wflow").write_text("old", encoding="utf-8")
            old_config = root / "config.env"
            old_config.write_text("old", encoding="utf-8")

            new_runtime = root / ".runtime.staging"
            new_runtime.mkdir()
            (new_runtime / "version.py").write_text("new", encoding="utf-8")
            new_workflow = root / ".workflow.staging.workflow"
            new_workflow.mkdir()
            (new_workflow / "document.wflow").write_text("new", encoding="utf-8")
            new_config = root / ".config.staging"
            new_config.write_text("new", encoding="utf-8")

            real_replace = os.replace

            def fail_workflow_publish(source, target):
                if Path(source) == new_workflow and Path(target) == old_workflow:
                    raise OSError("simulated workflow publish failure")
                return real_replace(source, target)

            with mock.patch.object(
                install_quick_action.os,
                "replace",
                side_effect=fail_workflow_publish,
            ):
                with self.assertRaises(OSError):
                    install_quick_action._publish_install_bundle([
                        (new_runtime, old_runtime),
                        (new_workflow, old_workflow),
                        (new_config, old_config),
                    ])

            self.assertEqual(
                (old_runtime / "version.py").read_text(encoding="utf-8"), "old"
            )
            self.assertEqual(
                (old_workflow / "document.wflow").read_text(encoding="utf-8"), "old"
            )
            self.assertEqual(old_config.read_text(encoding="utf-8"), "old")
            self.assertFalse(new_runtime.exists())
            self.assertFalse(new_workflow.exists())
            self.assertFalse(new_config.exists())

    @unittest.skipUnless(
        importlib.util.find_spec("PIL") is not None,
        "Pillow is optional",
    )
    def test_optimize_image_rejects_input_output_collision(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "same.png"
            Image.new("RGB", (2, 2), (255, 255, 255)).save(image_path)

            with self.assertRaises(OutputPathError):
                optimize_file.optimize_image(image_path, image_path)

    @unittest.skipUnless(
        importlib.util.find_spec("PIL") is not None,
        "Pillow is optional",
    )
    def test_optimize_image_preserves_alpha_when_output_is_png(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "alpha.png"
            output_path = Path(temp_dir) / "optimized.png"
            Image.new("RGBA", (4, 4), (255, 0, 0, 80)).save(input_path)

            optimize_file.optimize_image(input_path, output_path)

            with Image.open(output_path) as result:
                self.assertEqual(result.mode, "RGBA")
