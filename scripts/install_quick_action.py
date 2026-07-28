#!/usr/bin/env python3
"""Install a Finder Quick Action for background PaddleOCR conversion."""

import argparse
import ast
import getpass
import hashlib
import json
import math
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from lib import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_KEYCHAIN_ACCOUNT,
    DEFAULT_KEYCHAIN_SERVICE,
    DEFAULT_MODEL,
    MAX_TASK_TIMEOUT,
    read_local_config_values,
    resolve_api_url,
)
from safe_io import atomic_replace_directory, atomic_write_text
from version import VERSION


WORKFLOW_NAME = "转为 Markdown (OCR)"
WORKFLOW_PATH = Path.home() / "Library" / "Services" / f"{WORKFLOW_NAME}.workflow"
RUNTIME_DIR = Path.home() / "Library" / "Application Support" / "pdf-to-md"
SHELL_ACTION_TEMPLATE = Path(
    "/System/Library/Services/Show Map.workflow/Contents/Resources/document.wflow"
)
RUNNER_PATH = Path(__file__).resolve().parent / "run_quick_action.sh"
RUNTIME_COPY_FILES = (
    "lib.py",
    "vl_caller.py",
    "cli.py",
    "config.py",
    "input_files.py",
    "ocr_client.py",
    "response_parser.py",
    "artifacts.py",
    "cache_store.py",
    "pipeline.py",
    "split_pdf.py",
    "safe_io.py",
    "contracts.py",
    "pdf_to_md.py",
    "pdf_to_md_batch.py",
    "version.py",
    "run_quick_action.sh",
)
RUNTIME_PYTHON_FILE = "python-path"
RUNTIME_FILES = RUNTIME_COPY_FILES + (RUNTIME_PYTHON_FILE,)
RUNTIME_ENTRYPOINTS = ("vl_caller.py", "pdf_to_md.py", "pdf_to_md_batch.py")
WORKFLOW_FILE_TYPES = [
    "com.adobe.pdf",
    "public.png",
    "public.jpeg",
    "public.tiff",
    "com.microsoft.bmp",
    "org.webmproject.webp",
]


def _local_python_imports(path: Path, local_modules: set[str]) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module.split(".", 1)[0])
    return {name for name in imports if name in local_modules}


def _validate_runtime_dependency_closure(source_dir: Path) -> None:
    """Fail installation if the copied runtime omits a local import."""
    source_modules = {
        path.stem: path
        for path in source_dir.glob("*.py")
        if path.is_file()
    }
    graph = {
        name: _local_python_imports(path, set(source_modules))
        for name, path in source_modules.items()
    }
    needed = set()
    pending = [Path(entry).stem for entry in RUNTIME_ENTRYPOINTS]
    while pending:
        name = pending.pop()
        if name in needed:
            continue
        if name not in graph:
            raise RuntimeError(f"runtime entrypoint is missing: {name}.py")
        needed.add(name)
        pending.extend(graph[name] - needed)
    copied_modules = {
        Path(file_name).stem
        for file_name in RUNTIME_COPY_FILES
        if file_name.endswith(".py")
    }
    missing = sorted(f"{name}.py" for name in needed - copied_modules)
    if missing:
        raise RuntimeError(
            "runtime dependency manifest is incomplete: " + ", ".join(missing)
        )


def _validate_timeout(timeout: Optional[str]) -> None:
    if not timeout:
        return
    try:
        timeout_value = float(timeout)
    except ValueError as exc:
        raise ValueError("timeout must be a number of seconds") from exc
    if not math.isfinite(timeout_value) or not 1 <= timeout_value <= MAX_TASK_TIMEOUT:
        raise ValueError(f"timeout must be between 1 and {MAX_TASK_TIMEOUT} seconds")


def write_config(
    api_url: str,
    timeout: Optional[str],
    model: str = DEFAULT_MODEL,
    *,
    allow_insecure_http: bool = False,
) -> Path:
    config_text = _render_config(
        api_url,
        timeout,
        model,
        allow_insecure_http=allow_insecure_http,
    )
    atomic_write_text(
        DEFAULT_CONFIG_PATH,
        config_text,
        force=True,
    )
    DEFAULT_CONFIG_PATH.chmod(0o600)
    return DEFAULT_CONFIG_PATH


def _render_config(
    api_url: str,
    timeout: Optional[str],
    model: str = DEFAULT_MODEL,
    *,
    allow_insecure_http: bool = False,
) -> str:
    api_url, _ = resolve_api_url(api_url, allow_insecure_http=allow_insecure_http)
    values = read_local_config_values(DEFAULT_CONFIG_PATH)
    values["PADDLEOCR_DOC_PARSING_API_URL"] = api_url
    if model:
        values["PADDLEOCR_DOC_PARSING_MODEL"] = model
    if timeout:
        _validate_timeout(timeout)
        values["PADDLEOCR_DOC_PARSING_TIMEOUT"] = timeout
    if allow_insecure_http:
        values["PADDLEOCR_ALLOW_INSECURE_HTTP"] = "1"
    ordered_keys = (
        "PADDLEOCR_DOC_PARSING_API_URL",
        "PADDLEOCR_DOC_PARSING_MODEL",
        "PADDLEOCR_DOC_PARSING_TIMEOUT",
        "PADDLEOCR_DOC_PARSING_CONNECT_TIMEOUT",
        "PADDLEOCR_DOC_PARSING_MAX_RETRIES",
        "PADDLEOCR_DOC_PARSING_RETRY_BACKOFF",
        "PADDLEOCR_DOC_PARSING_MAX_LOCAL_FILE_MB",
        "PADDLEOCR_DOC_PARSING_MAX_REQUEST_MB",
        "PADDLEOCR_DOC_PARSING_MAX_RESPONSE_MB",
        "PADDLEOCR_DOC_PARSING_TASK_TIMEOUT",
        "PADDLEOCR_DOC_PARSING_MAX_PAGES_PER_REQUEST",
        "PADDLEOCR_DOC_PARSING_MAX_CHUNK_WORKERS",
        "PADDLEOCR_DOC_PARSING_CACHE_TTL_SECONDS",
        "PADDLEOCR_DOC_PARSING_CACHE_MAX_MB",
        "PADDLEOCR_DOC_PARSING_ASSET_TIMEOUT",
        "PADDLEOCR_DOC_PARSING_MAX_ASSET_COUNT",
        "PADDLEOCR_DOC_PARSING_MAX_ASSET_TOTAL_MB",
        "PADDLEOCR_DOC_PARSING_ASSET_TOTAL_TIMEOUT",
        "PADDLEOCR_ALLOW_INSECURE_HTTP",
    )
    lines = [f"{key}={values[key]}" for key in ordered_keys if key in values]
    return "\n".join(lines) + "\n"


def store_token_in_keychain(token: str) -> None:
    security_bin = shutil.which("security")
    if not security_bin:
        raise RuntimeError("macOS security command is not available")
    # Keep -w last so security reads the hidden password from its input stream.
    result = subprocess.run(
        [
            security_bin,
            "add-generic-password",
            "-s",
            DEFAULT_KEYCHAIN_SERVICE,
            "-a",
            DEFAULT_KEYCHAIN_ACCOUNT,
            "-U",
            "-w",
        ],
        input=f"{token}\n",
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError("Failed to store access token in Keychain")


def _stage_runtime_without_commit() -> tuple[Path, Path]:
    source_dir = Path(__file__).resolve().parent
    _validate_runtime_dependency_closure(source_dir)
    RUNTIME_DIR.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = RUNTIME_DIR.parent / f".{RUNTIME_DIR.name}.staging-{uuid.uuid4().hex}"
    staging_dir.mkdir(parents=True)
    try:
        for file_name in RUNTIME_COPY_FILES:
            shutil.copy2(source_dir / file_name, staging_dir / file_name)
        python_path = Path(sys.executable).resolve()
        if not python_path.is_file():
            raise RuntimeError(f"installer Python executable not found: {python_path}")
        (staging_dir / RUNTIME_PYTHON_FILE).write_text(
            str(python_path) + "\n",
            encoding="utf-8",
        )
        (staging_dir / RUNTIME_PYTHON_FILE).chmod(0o600)
        if any(not (staging_dir / file_name).is_file() for file_name in RUNTIME_FILES):
            raise RuntimeError("runtime staging validation failed")
        manifest = {
            "version": VERSION,
            "files": {},
        }
        for file_name in RUNTIME_FILES:
            digest = hashlib.sha256((staging_dir / file_name).read_bytes()).hexdigest()
            manifest["files"][file_name] = digest
        (staging_dir / "runtime-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (staging_dir / "runtime-manifest.json").chmod(0o600)
        (staging_dir / "run_quick_action.sh").chmod(0o755)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    return staging_dir, staging_dir / "run_quick_action.sh"


def install_runtime() -> Path:
    """Install only the runtime, retained for standalone maintenance use."""
    staging_dir, runner_path = _stage_runtime_without_commit()
    try:
        atomic_replace_directory(staging_dir, RUNTIME_DIR, force=True)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    return RUNTIME_DIR / runner_path.name


def _stage_workflow(runner_path: Path = RUNNER_PATH) -> Path:
    if not SHELL_ACTION_TEMPLATE.is_file():
        raise RuntimeError(f"Automator workflow template not found: {SHELL_ACTION_TEMPLATE}")
    WORKFLOW_PATH.parent.mkdir(parents=True, exist_ok=True)
    staging_path = WORKFLOW_PATH.parent / f".{WORKFLOW_PATH.stem}.staging-{uuid.uuid4().hex}.workflow"
    try:
        return _write_workflow_staging(staging_path, runner_path)
    except Exception:
        shutil.rmtree(staging_path, ignore_errors=True)
        raise


def _write_workflow_staging(staging_path: Path, runner_path: Path) -> Path:
    contents = staging_path / "Contents"
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
    command = f"{shlex.quote(str(runner_path))} \"$@\""
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
    return staging_path


def install_workflow(runner_path: Path = RUNNER_PATH) -> Path:
    """Install only the workflow, retained for standalone maintenance use."""
    staging_path = _stage_workflow(runner_path)
    try:
        atomic_replace_directory(staging_path, WORKFLOW_PATH, force=True)
        return WORKFLOW_PATH
    finally:
        if staging_path.exists():
            shutil.rmtree(staging_path, ignore_errors=True)


def _stage_config(
    api_url: str,
    timeout: Optional[str],
    model: str,
    *,
    allow_insecure_http: bool = False,
) -> Path:
    config_text = _render_config(
        api_url,
        timeout,
        model,
        allow_insecure_http=allow_insecure_http,
    )
    DEFAULT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{DEFAULT_CONFIG_PATH.name}.staging-",
        dir=str(DEFAULT_CONFIG_PATH.parent),
    )
    temp_path = Path(temp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(config_text)
            output.flush()
            os.fsync(output.fileno())
        return temp_path
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _remove_path(path: Path) -> None:
    if not os.path.lexists(str(path)):
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def _sync_parent(path: Path) -> None:
    try:
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _publish_install_bundle(staged_artifacts: list[tuple[Path, Path]]) -> None:
    """Commit runtime, workflow, and config together with rollback on failure."""
    records = []
    try:
        for staging_path, output_path in staged_artifacts:
            if not os.path.lexists(str(staging_path)):
                raise RuntimeError(f"staging artifact disappeared: {staging_path}")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            backup_path = output_path.parent / (
                f".{output_path.name}.previous-{os.getpid()}-{uuid.uuid4().hex}"
            )
            had_output = os.path.lexists(str(output_path))
            record = {
                "staging": staging_path,
                "output": output_path,
                "backup": backup_path,
                "had_output": had_output,
                "moved_output": False,
                "installed": False,
            }
            records.append(record)
            if had_output:
                os.replace(output_path, backup_path)
                record["moved_output"] = True
            os.replace(staging_path, output_path)
            record["installed"] = True
            _sync_parent(output_path)
    except Exception:
        for record in reversed(records):
            output_path = record["output"]
            backup_path = record["backup"]
            if record["installed"]:
                _remove_path(output_path)
            if record["moved_output"] and os.path.lexists(str(backup_path)):
                os.replace(backup_path, output_path)
                _sync_parent(output_path)
        raise
    finally:
        for record in records:
            _remove_path(record["backup"])
            _remove_path(record["staging"])
        for staging_path, _ in staged_artifacts:
            _remove_path(staging_path)


def install_bundle(
    api_url: str,
    timeout: Optional[str],
    model: str,
    *,
    allow_insecure_http: bool = False,
) -> tuple[Path, Path, Path]:
    """Stage and atomically publish all file-backed Finder installation artifacts."""
    staged: list[tuple[Path, Path]] = []
    try:
        runtime_staging, _ = _stage_runtime_without_commit()
        staged.append((runtime_staging, RUNTIME_DIR))
        workflow_staging = _stage_workflow(RUNTIME_DIR / "run_quick_action.sh")
        staged.append((workflow_staging, WORKFLOW_PATH))
        config_staging = _stage_config(
            api_url,
            timeout,
            model,
            allow_insecure_http=allow_insecure_http,
        )
        staged.append((config_staging, DEFAULT_CONFIG_PATH))
        _publish_install_bundle(staged)
    except Exception:
        for staging_path, _ in staged:
            _remove_path(staging_path)
        raise
    return RUNTIME_DIR / "run_quick_action.sh", WORKFLOW_PATH, DEFAULT_CONFIG_PATH


def refresh_services() -> bool:
    pbs = Path("/System/Library/CoreServices/pbs")
    if not pbs.exists():
        return True
    try:
        results = [
            subprocess.run([str(pbs), "-flush"], check=False, capture_output=True),
            subprocess.run([str(pbs), "-update"], check=False, capture_output=True),
        ]
    except OSError:
        return False
    return all(result.returncode == 0 for result in results)


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
    parser.add_argument(
        "--store-token",
        action="store_true",
        help="Prompt for the API token and store it in macOS Keychain",
    )
    parser.add_argument(
        "--allow-insecure-http",
        action="store_true",
        help="Allow HTTP only for loopback development endpoints",
    )
    args = parser.parse_args()

    if sys.platform != "darwin":
        parser.error("Finder Quick Action installation is supported only on macOS")
    if not args.api_url:
        parser.error("Provide --api-url or set PADDLEOCR_DOC_PARSING_API_URL")
    try:
        resolve_api_url(args.api_url, allow_insecure_http=args.allow_insecure_http)
        _validate_timeout(args.timeout or None)
    except ValueError as exc:
        parser.error(str(exc))

    if args.store_env_token and args.store_token:
        parser.error("Choose only one of --store-env-token and --store-token")
    token_to_store = None
    try:
        if args.store_env_token:
            token_to_store = os.getenv("PADDLEOCR_ACCESS_TOKEN", "").strip()
            if not token_to_store:
                parser.error("--store-env-token requires PADDLEOCR_ACCESS_TOKEN in the environment")
        elif args.store_token:
            token_to_store = getpass.getpass("PaddleOCR access token: ").strip()
            if not token_to_store:
                parser.error("--store-token requires a non-empty token")

        runner_path, workflow_path, config_path = install_bundle(
            args.api_url,
            args.timeout or None,
            args.model,
            allow_insecure_http=args.allow_insecure_http,
        )
    except Exception as exc:
        print(f"Installation failed; existing Finder files were preserved: {exc}", file=sys.stderr)
        return 1
    if token_to_store is not None:
        try:
            store_token_in_keychain(token_to_store)
        except Exception as exc:
            print(
                "Finder files were installed, but the access token could not be stored in Keychain: "
                f"{exc}",
                file=sys.stderr,
            )
            return 2
    refresh_ok = refresh_services()
    print(f"Installed Finder Quick Action: {workflow_path}")
    print(f"Installed runtime scripts: {RUNTIME_DIR}")
    print(f"Local config written: {config_path}")
    if args.store_env_token or args.store_token:
        print(f"Access token stored in Keychain service: {DEFAULT_KEYCHAIN_SERVICE}")
    if not refresh_ok:
        print("Finder refresh is pending; reopen Finder or enable the Quick Action in System Settings.")
        return 2
    print("In Finder: select PDF or image files, then use Quick Actions > 转为 Markdown (OCR).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
