#!/usr/bin/env python3
"""Install a Finder Quick Action for background PaddleOCR conversion."""

import argparse
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from lib import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_KEYCHAIN_ACCOUNT,
    DEFAULT_KEYCHAIN_SERVICE,
    DEFAULT_MODEL,
)


WORKFLOW_NAME = "转为 Markdown (OCR)"
WORKFLOW_PATH = Path.home() / "Library" / "Services" / f"{WORKFLOW_NAME}.workflow"
RUNTIME_DIR = Path.home() / "Library" / "Application Support" / "pdf-to-md"
SHELL_ACTION_TEMPLATE = Path(
    "/System/Library/Services/Show Map.workflow/Contents/Resources/document.wflow"
)
RUNNER_PATH = Path(__file__).resolve().parent / "run_quick_action.sh"
RUNTIME_FILES = (
    "lib.py",
    "vl_caller.py",
    "split_pdf.py",
    "pdf_to_md.py",
    "pdf_to_md_batch.py",
    "run_quick_action.sh",
)
WORKFLOW_FILE_TYPES = ["com.adobe.pdf", "public.image"]


def write_config(api_url: str, timeout: Optional[str], model: str = DEFAULT_MODEL) -> Path:
    if not api_url.rstrip("/").endswith("/layout-parsing"):
        raise ValueError("API URL must end with /layout-parsing")
    lines = [f"PADDLEOCR_DOC_PARSING_API_URL={api_url}"]
    if model:
        lines.append(f"PADDLEOCR_DOC_PARSING_MODEL={model}")
    if timeout:
        lines.append(f"PADDLEOCR_DOC_PARSING_TIMEOUT={timeout}")
    DEFAULT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_CONFIG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    DEFAULT_CONFIG_PATH.chmod(0o600)
    return DEFAULT_CONFIG_PATH


def store_token_in_keychain(token: str) -> None:
    security_bin = shutil.which("security")
    if not security_bin:
        raise RuntimeError("macOS security command is not available")
    subprocess.run(
        [
            security_bin,
            "add-generic-password",
            "-s",
            DEFAULT_KEYCHAIN_SERVICE,
            "-a",
            DEFAULT_KEYCHAIN_ACCOUNT,
            "-w",
            token,
            "-U",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def install_runtime() -> Path:
    source_dir = Path(__file__).resolve().parent
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    for file_name in RUNTIME_FILES:
        shutil.copy2(source_dir / file_name, RUNTIME_DIR / file_name)
    (RUNTIME_DIR / "run_quick_action.sh").chmod(0o755)
    return RUNTIME_DIR / "run_quick_action.sh"


def install_workflow(runner_path: Path = RUNNER_PATH) -> Path:
    if not SHELL_ACTION_TEMPLATE.is_file():
        raise RuntimeError(f"Automator workflow template not found: {SHELL_ACTION_TEMPLATE}")
    contents = WORKFLOW_PATH / "Contents"
    if WORKFLOW_PATH.exists():
        shutil.rmtree(WORKFLOW_PATH)
    contents.mkdir(parents=True)

    info = {
        "NSServices": [
            {
                "NSBackgroundColorName": "background",
                "NSIconName": "NSActionTemplate",
                "NSMenuItem": {"default": WORKFLOW_NAME},
                "NSMessage": "runWorkflowAsService",
                "NSSendFileTypes": WORKFLOW_FILE_TYPES,
            }
        ],
    }
    with (contents / "Info.plist").open("wb") as output:
        plistlib.dump(info, output)

    with SHELL_ACTION_TEMPLATE.open("rb") as source:
        workflow = plistlib.load(source)
    action = workflow["actions"][0]["action"]
    command = (
        f"PDF_TO_MD_PYTHON={shlex.quote(sys.executable)} "
        f"{shlex.quote(str(runner_path))} \"$@\""
    )
    action["ActionParameters"]["COMMAND_STRING"] = command
    action["ActionParameters"]["inputMethod"] = 1
    action["ActionParameters"]["shell"] = "/bin/bash"
    workflow["workflowMetaData"] = {
        "applicationBundleIDsByPath": {},
        "applicationPaths": [],
        "inputTypeIdentifier": "com.apple.Automator.fileSystemObject",
        "outputTypeIdentifier": "com.apple.Automator.nothing",
        "presentationMode": 15,
        "processesInput": False,
        "serviceInputTypeIdentifier": "com.apple.Automator.fileSystemObject",
        "serviceOutputTypeIdentifier": "com.apple.Automator.nothing",
        "serviceProcessesInput": False,
        "systemImageName": "NSActionTemplate",
        "useAutomaticInputType": False,
        "workflowTypeIdentifier": "com.apple.Automator.servicesMenu",
    }
    with (contents / "document.wflow").open("wb") as output:
        plistlib.dump(workflow, output)
    return WORKFLOW_PATH


def refresh_services() -> None:
    pbs = Path("/System/Library/CoreServices/pbs")
    if pbs.exists():
        subprocess.run([str(pbs), "-flush"], check=False, capture_output=True)
        subprocess.run([str(pbs), "-update"], check=False, capture_output=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the PDF/image to Markdown Finder Quick Action.")
    parser.add_argument(
        "--api-url",
        default=os.getenv("PADDLEOCR_DOC_PARSING_API_URL", ""),
        help="PaddleOCR layout-parsing endpoint; defaults to the current environment",
    )
    parser.add_argument(
        "--timeout",
        default=os.getenv("PADDLEOCR_DOC_PARSING_TIMEOUT", ""),
        help="Optional API timeout written to local config",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("PADDLEOCR_DOC_PARSING_MODEL", DEFAULT_MODEL),
        help=f"PaddleOCR official API model; defaults to {DEFAULT_MODEL}",
    )
    parser.add_argument(
        "--store-env-token",
        action="store_true",
        help="Store PADDLEOCR_ACCESS_TOKEN from the current environment in macOS Keychain",
    )
    args = parser.parse_args()

    if sys.platform != "darwin":
        parser.error("Finder Quick Action installation is supported only on macOS")
    if not args.api_url:
        parser.error("Provide --api-url or set PADDLEOCR_DOC_PARSING_API_URL")

    config_path = write_config(args.api_url, args.timeout or None, args.model)
    if args.store_env_token:
        token = os.getenv("PADDLEOCR_ACCESS_TOKEN", "").strip()
        if not token:
            parser.error("--store-env-token requires PADDLEOCR_ACCESS_TOKEN in the environment")
        store_token_in_keychain(token)

    runner_path = install_runtime()
    workflow_path = install_workflow(runner_path)
    refresh_services()
    print(f"Installed Finder Quick Action: {workflow_path}")
    print(f"Installed runtime scripts: {RUNTIME_DIR}")
    print(f"Local config written: {config_path}")
    if args.store_env_token:
        print(f"Access token stored in Keychain service: {DEFAULT_KEYCHAIN_SERVICE}")
    print("In Finder: select PDF or image files, then use Quick Actions > 转为 Markdown (OCR).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
