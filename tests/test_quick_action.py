from test_support import *

class QuickActionTests(unittest.TestCase):
    def test_batch_runner_converts_files_sequentially_and_writes_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "input.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nsample\n")
            log_path = Path(temp_dir) / "run.log"

            def fake_run(cmd, **kwargs):
                if "pdf_to_md.py" in str(cmd[1]):
                    output_path = Path(cmd[cmd.index("--markdown-output") + 1])
                    output_path.write_text("converted\n", encoding="utf-8")
                return SimpleNamespace(returncode=0)

            with mock.patch.dict(
                os.environ, {"PDF_TO_MD_LOG_FILE": str(log_path)}, clear=False
            ):
                with mock.patch("pdf_to_md_batch.subprocess.run", side_effect=fake_run):
                    exit_code = pdf_to_md_batch.main([str(pdf_path)])

            status = json.loads(log_path.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(status["state"], "completed")
            self.assertEqual(status["terminal_status"], "completed")
            self.assertTrue(status["results"][0]["ok"])
            self.assertEqual(
                Path(status["results"][0]["output"]),
                pdf_path.resolve().with_name("input.pdf.md"),
            )

    def test_batch_runner_converts_image_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "scan.png"
            image_path.write_bytes(b"\x89PNG\r\n\x1a\nsample\n")
            log_path = Path(temp_dir) / "run.log"

            def fake_run(cmd, **kwargs):
                if "pdf_to_md.py" in str(cmd[1]):
                    output_path = Path(cmd[cmd.index("--markdown-output") + 1])
                    output_path.write_text("converted\n", encoding="utf-8")
                return SimpleNamespace(returncode=0)

            with mock.patch.dict(
                os.environ, {"PDF_TO_MD_LOG_FILE": str(log_path)}, clear=False
            ):
                with mock.patch("pdf_to_md_batch.subprocess.run", side_effect=fake_run) as run_mock:
                    exit_code = pdf_to_md_batch.main([str(image_path)])

            status = json.loads(log_path.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(status["state"], "completed")
            self.assertTrue(status["results"][0]["ok"])
            self.assertEqual(
                Path(status["results"][0]["output"]),
                image_path.resolve().with_name("scan.png.md"),
            )
            ocr_call = next(
                call for call in run_mock.call_args_list
                if "pdf_to_md.py" in str(call.args[0][1])
            )
            self.assertNotIn("timeout", ocr_call.kwargs)

    def test_batch_runner_publishes_staged_asset_directory_with_final_reference_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "scan.png"
            image_path.write_bytes(b"\x89PNG\r\n\x1a\nsample\n")
            log_path = Path(temp_dir) / "run.log"

            def fake_run(cmd, **kwargs):
                if "pdf_to_md.py" not in str(cmd[1]):
                    return SimpleNamespace(returncode=0)
                output_path = Path(cmd[cmd.index("--markdown-output") + 1])
                assets_path = Path(cmd[cmd.index("--assets-output") + 1])
                reference_name = cmd[cmd.index("--assets-reference-name") + 1]
                output_path.write_text(
                    f"![figure]({reference_name}/figure.png)\n",
                    encoding="utf-8",
                )
                assets_path.mkdir()
                (assets_path / "figure.png").write_bytes(b"asset")
                return SimpleNamespace(returncode=0)

            with mock.patch.dict(
                os.environ, {"PDF_TO_MD_LOG_FILE": str(log_path)}, clear=False
            ):
                with mock.patch("pdf_to_md_batch.subprocess.run", side_effect=fake_run):
                    exit_code = pdf_to_md_batch.main([str(image_path)])

            output_path = image_path.with_name("scan.png.md")
            asset_dir = image_path.with_name("scan.png.assets")
            self.assertEqual(exit_code, 0)
            self.assertIn("scan.png.assets/figure.png", output_path.read_text(encoding="utf-8"))
            self.assertTrue((asset_dir / "figure.png").is_file())

    def test_batch_runner_does_not_treat_stale_markdown_as_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "input.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nsample\n")
            stale_output = pdf_path.with_name("input.pdf.md")
            stale_output.write_text("old\n", encoding="utf-8")
            log_path = Path(temp_dir) / "run.log"

            def fake_run(cmd, **kwargs):
                return SimpleNamespace(returncode=0)

            with mock.patch.dict(
                os.environ, {"PDF_TO_MD_LOG_FILE": str(log_path)}, clear=False
            ):
                with mock.patch("pdf_to_md_batch.subprocess.run", side_effect=fake_run):
                    exit_code = pdf_to_md_batch.main([str(pdf_path)])

            status = json.loads(log_path.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 1)
            self.assertEqual(status["state"], "failed")

    def test_batch_runner_does_not_leave_stale_assets_on_new_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "input.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nsample\n")
            asset_dir = pdf_path.with_name("input.pdf.assets")
            asset_dir.mkdir()
            (asset_dir / "stale.png").write_bytes(b"stale")
            log_path = Path(temp_dir) / "run.log"

            def fake_run(cmd, **kwargs):
                if "--markdown-output" not in cmd:
                    return SimpleNamespace(returncode=0)
                output_path = Path(cmd[cmd.index("--markdown-output") + 1])
                output_path.write_text("new\n", encoding="utf-8")
                return SimpleNamespace(returncode=0)

            with mock.patch.dict(
                os.environ, {"PDF_TO_MD_LOG_FILE": str(log_path)}, clear=False
            ):
                with mock.patch("pdf_to_md_batch.subprocess.run", side_effect=fake_run):
                    exit_code = pdf_to_md_batch.main([str(pdf_path)])

            status = json.loads(log_path.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 1)
            self.assertEqual(status["state"], "failed")
            self.assertTrue((asset_dir / "stale.png").exists())

    def test_batch_runner_records_running_state_before_work(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "input.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nsample\n")
            log_path = Path(temp_dir) / "run.log"
            captured = {}

            def fake_run_batch(paths, passed_log_path, **kwargs):
                captured.update(
                    json.loads(log_path.with_suffix(".json").read_text(encoding="utf-8"))
                )
                return [], 0

            with mock.patch.dict(
                os.environ, {"PDF_TO_MD_LOG_FILE": str(log_path)}, clear=False
            ):
                with mock.patch("pdf_to_md_batch.run_batch", side_effect=fake_run_batch):
                    pdf_to_md_batch.main([str(pdf_path)])

            self.assertEqual(captured["state"], "running")
            self.assertEqual(captured["files"][0]["path"], str(pdf_path.resolve()))

    def test_batch_runner_displays_foreground_alert_for_failed_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "broken.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nsample\n")
            log_path = Path(temp_dir) / "run.log"

            with mock.patch.dict(
                os.environ, {"PDF_TO_MD_LOG_FILE": str(log_path)}, clear=False
            ):
                with mock.patch("pdf_to_md_batch.run_batch", return_value=(
                    [{"file": str(pdf_path), "output": str(pdf_path.with_suffix(".md")), "ok": False}],
                    1,
                )):
                    with mock.patch("pdf_to_md_batch.alert_failure") as alert_mock:
                        exit_code = pdf_to_md_batch.main([str(pdf_path)])

            status = json.loads(log_path.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 1)
            self.assertEqual(status["state"], "failed")
            alert_mock.assert_called_once()
            self.assertIn("broken.pdf", alert_mock.call_args.args[0])

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS Automator template")
    def test_installer_generates_native_pdf_and_image_quick_action_workflow(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workflow_path = Path(temp_dir) / "Quick Action.workflow"
            runner_path = Path(temp_dir) / "run_quick_action.sh"
            with mock.patch.object(install_quick_action, "WORKFLOW_PATH", workflow_path):
                installed_path = install_quick_action.install_workflow(runner_path)

            with (installed_path / "Contents" / "Info.plist").open("rb") as source:
                info = plistlib.load(source)
            with (installed_path / "Contents" / "document.wflow").open("rb") as source:
                workflow = plistlib.load(source)

            self.assertEqual(
                info["NSServices"][0]["NSSendFileTypes"],
                [
                    "com.adobe.pdf",
                    "public.png",
                    "public.jpeg",
                    "public.tiff",
                    "com.microsoft.bmp",
                    "org.webmproject.webp",
                ],
            )
            self.assertEqual(info["NSServices"][0]["NSIconName"], "NSActionTemplate")
            command = workflow["actions"][0]["action"]["ActionParameters"]["COMMAND_STRING"]
            self.assertIn(str(runner_path), command)
            self.assertNotIn("PDF_TO_MD_PYTHON=", command)
            self.assertEqual(
                workflow["workflowMetaData"]["serviceInputTypeIdentifier"],
                "com.apple.Automator.fileSystemObject",
            )
            self.assertEqual(workflow["workflowMetaData"]["presentationMode"], 15)
            self.assertNotIn("serviceApplicationBundleID", workflow["workflowMetaData"])

    def test_installer_runtime_includes_split_pdf_dependency(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir) / "runtime"
            with mock.patch.object(install_quick_action, "RUNTIME_DIR", runtime_dir):
                runner_path = install_quick_action.install_runtime()

            for file_name in install_quick_action.RUNTIME_FILES:
                self.assertTrue(
                    (runtime_dir / file_name).is_file(),
                    file_name,
                )
            manifest_path = runtime_dir / "runtime-manifest.json"
            self.assertTrue(manifest_path.is_file())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                set(manifest["files"]),
                set(install_quick_action.RUNTIME_FILES),
            )
            self.assertEqual(runner_path, runtime_dir / "run_quick_action.sh")
            self.assertEqual(
                (runtime_dir / "python-path").read_text(encoding="utf-8").strip(),
                str(Path(sys.executable).resolve()),
            )
            runner = (runtime_dir / "run_quick_action.sh").read_text(encoding="utf-8")
            self.assertIn('"$SCRIPT_DIR/python-path"', runner)
            self.assertIn("import httpx, pypdf", runner)

    def test_installer_rejects_incomplete_runtime_dependency_manifest(self):
        source_dir = Path(install_quick_action.__file__).resolve().parent
        incomplete = tuple(
            file_name
            for file_name in install_quick_action.RUNTIME_COPY_FILES
            if file_name != "config.py"
        )
        with mock.patch.object(install_quick_action, "RUNTIME_COPY_FILES", incomplete):
            with self.assertRaisesRegex(RuntimeError, "config.py"):
                install_quick_action._validate_runtime_dependency_closure(source_dir)

    def test_installer_writes_model_to_local_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.env"
            with mock.patch.object(install_quick_action, "DEFAULT_CONFIG_PATH", config_path):
                install_quick_action.write_config(
                    "https://example.com/layout-parsing",
                    "120",
                    "PaddleOCR-VL-1.6",
                )

            content = config_path.read_text(encoding="utf-8")
            self.assertIn("PADDLEOCR_DOC_PARSING_MODEL=PaddleOCR-VL-1.6", content)

    def test_installer_preserves_supported_local_tuning_without_secrets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.env"
            config_path.write_text(
                "PADDLEOCR_DOC_PARSING_MAX_RETRIES=4\n"
                "PADDLEOCR_DOC_PARSING_MAX_PAGES_PER_REQUEST=10\n"
                "PADDLEOCR_ACCESS_TOKEN=must-not-be-copied\n",
                encoding="utf-8",
            )
            with mock.patch.object(install_quick_action, "DEFAULT_CONFIG_PATH", config_path):
                install_quick_action.write_config(
                    "https://example.com/layout-parsing",
                    None,
                    "PaddleOCR-VL-1.6",
                )

            content = config_path.read_text(encoding="utf-8")
            self.assertIn("PADDLEOCR_DOC_PARSING_MAX_RETRIES=4", content)
            self.assertIn("PADDLEOCR_DOC_PARSING_MAX_PAGES_PER_REQUEST=10", content)
            self.assertNotIn("PADDLEOCR_ACCESS_TOKEN", content)

    def test_keychain_failure_exception_does_not_include_token(self):
        sentinel = "secret-token-should-not-leak"
        failed = SimpleNamespace(returncode=1, stderr="bad", stdout="")
        with mock.patch("install_quick_action.shutil.which", return_value="/usr/bin/security"):
            with mock.patch("install_quick_action.subprocess.run", return_value=failed) as run_mock:
                with self.assertRaises(RuntimeError) as ctx:
                    install_quick_action.store_token_in_keychain(sentinel)

        self.assertNotIn(sentinel, str(ctx.exception))
        command = run_mock.call_args.args[0]
        self.assertIn("-w", command)
        self.assertNotIn(sentinel, command)
        self.assertEqual(run_mock.call_args.kwargs["input"], sentinel + "\n")
