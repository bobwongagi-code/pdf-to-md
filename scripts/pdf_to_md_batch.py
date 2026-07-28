#!/usr/bin/env python3
"""Sequential background-friendly document/image to Markdown conversion entry point."""

import os
import hashlib
import shutil
import threading
import uuid
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from lib import IMAGE_EXTENSIONS
from safe_io import (
    OutputPathError,
    atomic_replace,
    atomic_replace_directory,
    atomic_write_json,
)


SCRIPT_DIR = Path(__file__).resolve().parent
LOG_DIR = Path.home() / "Library" / "Logs" / "pdf-to-md"
SUPPORTED_EXTENSIONS = (".pdf",) + IMAGE_EXTENSIONS


def _is_supported_input(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def _input_entry_path(path: str) -> Path:
    entry = Path(path).expanduser()
    if entry.is_symlink():
        return entry.absolute()
    return entry.resolve()


def notify(title: str, message: str) -> None:
    if sys.platform != "darwin":
        return
    script = (
        "on run argv\n"
        "display notification (item 2 of argv) with title (item 1 of argv)\n"
        "end run"
    )
    subprocess.run(
        ["/usr/bin/osascript", "-e", script, title, message],
        check=False,
        capture_output=True,
        text=True,
    )


def alert_failure(message: str, log_path: Path) -> None:
    """Present a foreground error with a direct path to the diagnostic log."""
    if sys.platform != "darwin":
        return
    script = (
        "on run argv\n"
        'set choice to display alert "PDF 转 Markdown 失败" '
        'message (item 1 of argv) as critical buttons {"查看日志", "好"} '
        'default button "好"\n'
        'if button returned of choice is "查看日志" then\n'
        'do shell script "/usr/bin/open -R " & quoted form of (item 2 of argv)\n'
        "end if\n"
        "end run"
    )
    subprocess.run(
        ["/usr/bin/osascript", "-e", script, message, str(log_path)],
        check=False,
        capture_output=True,
        text=True,
    )


def write_status(status_path: Path, status: dict) -> None:
    atomic_write_json(status_path, status, indent=2, force=True)


def _source_identity(path: Path, *, include_digest: bool = True) -> dict:
    try:
        stat = path.stat()
        identity = {
            "path": str(path),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
        if not include_digest:
            return identity
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        identity["sha256"] = digest.hexdigest()
        return identity
    except OSError as exc:
        return {"path": str(path), "error": str(exc)}


def run_batch(
    paths: list[Path],
    log_path: Path,
    *,
    run_id: Optional[str] = None,
    status_callback=None,
) -> tuple[list[dict], int]:
    results = []
    failed = 0
    run_id = run_id or uuid.uuid4().hex
    with log_path.open("a", encoding="utf-8") as log:
        try:
            log_path.chmod(0o600)
        except OSError:
            pass
        for index, path in enumerate(paths, start=1):
            output_path = path.with_name(f"{path.name}.md")
            if not path.is_file() or not _is_supported_input(path):
                result = {"file": str(path), "ok": False, "error": "not a supported PDF or image file"}
                results.append(result)
                failed += 1
                print(f"Skipping unsupported input: {path}", file=log, flush=True)
                if status_callback:
                    status_callback(results)
                continue

            print(f"Starting OCR: {path}", file=log, flush=True)
            notify("PDF to Markdown", f"正在处理 {index}/{len(paths)}: {path.name}")
            work_output_path = output_path.with_name(
                f".{output_path.name}.{run_id}.{index}.part.md"
            )
            asset_output_path = output_path.with_name(f"{output_path.stem}.assets")
            work_asset_output_path = output_path.with_name(
                f".{asset_output_path.name}.{run_id}.{index}.part"
            )
            cmd = [
                sys.executable,
                str(SCRIPT_DIR / "pdf_to_md.py"),
                str(path),
                "--markdown-output",
                str(work_output_path),
                "--assets-output",
                str(work_asset_output_path),
                "--assets-reference-name",
                asset_output_path.name,
                "--pretty",
            ]
            try:
                completed = subprocess.run(
                    cmd,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                )
            except Exception as e:
                work_output_path.unlink(missing_ok=True)
                if work_asset_output_path.exists():
                    shutil.rmtree(work_asset_output_path, ignore_errors=True)
                result = {
                    "file": str(path),
                    "source_identity": _source_identity(path, include_digest=False),
                    "output": str(output_path),
                    "output_sha256": None,
                    "ok": False,
                    "error_code": "START_FAILED",
                    "error": f"conversion failed to start: {e}",
                }
                results.append(result)
                failed += 1
                print(f"Failed to run conversion for {path}: {e}", file=log, flush=True)
                if status_callback:
                    status_callback(results)
                continue
            ok = False
            error = None
            output_digest = None
            published_asset_path = None
            if completed.returncode == 0 and work_output_path.is_file():
                try:
                    if work_output_path.stat().st_size <= 0:
                        raise ValueError("conversion produced an empty Markdown file")
                    if os.path.lexists(str(output_path)):
                        raise OutputPathError(
                            f"Markdown output already exists: {output_path}"
                        )
                    if os.path.lexists(str(asset_output_path)):
                        raise OutputPathError(
                            f"Markdown asset directory already exists: {asset_output_path}"
                        )
                    if work_asset_output_path.is_dir():
                        atomic_replace_directory(
                            work_asset_output_path,
                            asset_output_path,
                            force=False,
                        )
                        published_asset_path = asset_output_path
                    atomic_replace(work_output_path, output_path, force=False)
                    output_digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
                    ok = True
                except (OSError, OutputPathError, ValueError) as exc:
                    error = str(exc)
                    if published_asset_path is not None:
                        shutil.rmtree(published_asset_path, ignore_errors=True)
            elif completed.returncode != 0:
                error = f"conversion exited with status {completed.returncode}"
            else:
                error = "conversion exited successfully but produced no Markdown file"
            work_output_path.unlink(missing_ok=True)
            if work_asset_output_path.exists():
                shutil.rmtree(work_asset_output_path, ignore_errors=True)
            result = {
                "file": str(path),
                "source_identity": _source_identity(path),
                "output": str(output_path),
                "output_sha256": output_digest,
                "ok": ok,
            }
            if not ok:
                result["error_code"] = "CONVERSION_FAILED"
                result["error"] = error or "conversion failed"
                failed += 1
            results.append(result)
            print(f"Completed OCR: {path} ok={ok}", file=log, flush=True)
            if status_callback:
                status_callback(results)
    return results, failed


def main(argv: Optional[List[str]] = None) -> int:
    raw_paths = sys.argv[1:] if argv is None else argv
    if not raw_paths:
        notify("PDF to Markdown", "No PDF files were selected.")
        return 2

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    default_log_path = LOG_DIR / f"quick-action-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    log_path = Path(os.environ.get("PDF_TO_MD_LOG_FILE", default_log_path)).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    status_path = log_path.with_suffix(".json")
    # Preserve the selected entry itself so the child can enforce the default
    # no-symlink input policy instead of silently following it here.
    paths = [_input_entry_path(path) for path in raw_paths]
    started_at = datetime.now().isoformat(timespec="seconds")
    run_id = uuid.uuid4().hex
    status_lock = threading.Lock()
    status_state = {
        "state": "running",
        "terminal_status": "running",
        "run_id": run_id,
        "started_at": started_at,
        "heartbeat_at": started_at,
        "finished_at": None,
        "pid": os.getpid(),
        "log": str(log_path),
        "files": [_source_identity(path, include_digest=False) for path in paths],
        "results": [],
    }

    def write_progress(results):
        with status_lock:
            status_state["heartbeat_at"] = datetime.now().isoformat(timespec="seconds")
            status_state["results"] = list(results)
            write_status(status_path, dict(status_state))

    write_status(status_path, dict(status_state))

    heartbeat_stop = threading.Event()

    def heartbeat_loop():
        while not heartbeat_stop.wait(15):
            write_progress(status_state.get("results", []))

    heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    heartbeat_thread.start()
    try:
        results, failed = run_batch(
            paths,
            log_path,
            run_id=run_id,
            status_callback=write_progress,
        )
    except Exception as e:
        results = [
            {
                "file": str(path),
                "source_identity": _source_identity(path, include_digest=False),
                "ok": False,
                "error_code": "BATCH_CRASH",
                "error": f"batch crashed: {e}",
            }
            for path in paths
        ]
        failed = len(results)
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=2)
    status = {
        "state": "failed" if failed else "completed",
        "terminal_status": "failed" if failed else "completed",
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "heartbeat_at": datetime.now().isoformat(timespec="seconds"),
        "pid": os.getpid(),
        "log": str(log_path),
        "files": [_source_identity(path, include_digest=False) for path in paths],
        "results": results,
    }
    write_status(status_path, status)

    succeeded = len(results) - failed
    if failed:
        failed_names = ", ".join(
            Path(result["file"]).name for result in results if not result["ok"]
        )
        alert_failure(
            f"{failed} 个文件转换失败：{failed_names}\n\n日志已保存，可点击查看日志。",
            log_path,
        )
        return 1
    notify("PDF to Markdown", f"Completed: {succeeded} Markdown file(s) generated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
