#!/usr/bin/env python3
"""Sequential background-friendly document/image to Markdown conversion entry point."""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from lib import IMAGE_EXTENSIONS


SCRIPT_DIR = Path(__file__).resolve().parent
LOG_DIR = Path.home() / "Library" / "Logs" / "pdf-to-md"
OCR_TIMEOUT_BASE_SECONDS = 60
OCR_TIMEOUT_PER_PAGE_SECONDS = 30
OCR_TIMEOUT_MAX_SECONDS = 1800
SUPPORTED_EXTENSIONS = (".pdf",) + IMAGE_EXTENSIONS


def _is_supported_input(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def _ocr_timeout_for_file(path: Path) -> int:
    """Calculate timeout: 60s base + 30s per page, capped at 1800s."""
    if path.suffix.lower() != ".pdf":
        return OCR_TIMEOUT_MAX_SECONDS
    try:
        from pypdf import PdfReader
        page_count = len(PdfReader(str(path)).pages)
    except Exception:
        return OCR_TIMEOUT_MAX_SECONDS
    return min(OCR_TIMEOUT_BASE_SECONDS + OCR_TIMEOUT_PER_PAGE_SECONDS * page_count, OCR_TIMEOUT_MAX_SECONDS)


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
    status_path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_batch(paths: list[Path], log_path: Path) -> tuple[list[dict], int]:
    results = []
    failed = 0
    with log_path.open("a", encoding="utf-8") as log:
        for index, path in enumerate(paths, start=1):
            output_path = path.with_suffix(".md")
            if not path.is_file() or not _is_supported_input(path):
                result = {"file": str(path), "ok": False, "error": "not a supported PDF or image file"}
                results.append(result)
                failed += 1
                print(f"Skipping unsupported input: {path}", file=log, flush=True)
                continue

            print(f"Starting OCR: {path}", file=log, flush=True)
            notify("PDF to Markdown", f"正在处理 {index}/{len(paths)}: {path.name}")
            timeout_seconds = _ocr_timeout_for_file(path)
            cmd = [
                sys.executable,
                str(SCRIPT_DIR / "pdf_to_md.py"),
                str(path),
                "--chunk-pages",
                "20",
                "--chunk-workers",
                "1",
                "--pretty",
            ]
            try:
                completed = subprocess.run(
                    cmd,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                    timeout=timeout_seconds,
                )
            except subprocess.TimeoutExpired:
                result = {"file": str(path), "ok": False, "error": f"conversion timed out after {timeout_seconds}s"}
                results.append(result)
                failed += 1
                print(f"Timed out after {timeout_seconds}s: {path}", file=log, flush=True)
                continue
            ok = completed.returncode == 0 and output_path.is_file() and output_path.stat().st_size > 0
            result = {"file": str(path), "output": str(output_path), "ok": ok}
            if not ok:
                result["error"] = f"conversion exited with status {completed.returncode}"
                failed += 1
            results.append(result)
            print(f"Completed OCR: {path} ok={ok}", file=log, flush=True)
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
    paths = [Path(path).expanduser().resolve() for path in raw_paths]
    started_at = datetime.now().isoformat(timespec="seconds")
    write_status(
        status_path,
        {
            "state": "running",
            "started_at": started_at,
            "log": str(log_path),
            "files": [str(path) for path in paths],
        },
    )
    results, failed = run_batch(paths, log_path)
    status = {
        "state": "failed" if failed else "completed",
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "log": str(log_path),
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
