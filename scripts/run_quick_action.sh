#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$HOME/Library/Logs/pdf-to-md"
PYTHON_BIN="${PDF_TO_MD_PYTHON:-}"
if [[ -z "$PYTHON_BIN" && -r "$SCRIPT_DIR/python-path" ]]; then
  IFS= read -r PYTHON_BIN <"$SCRIPT_DIR/python-path"
fi
: "${PYTHON_BIN:=python3}"
mkdir -p "$LOG_DIR"

if [[ "$#" -eq 0 ]]; then
  /usr/bin/osascript -e 'display notification "No PDF or image files were selected." with title "PDF to Markdown"' >/dev/null 2>&1 || true
  exit 2
fi

LOG_FILE="$LOG_DIR/quick-action-$(date '+%Y%m%d-%H%M%S')-$$.log"
if ! "$PYTHON_BIN" -c 'import httpx, pypdf' >>"$LOG_FILE" 2>&1; then
  /usr/bin/osascript - "$LOG_FILE" <<'APPLESCRIPT' >/dev/null 2>&1 || true
on run argv
  display alert "PDF to Markdown 无法启动" message ¬
    ("Finder 使用的 Python 环境缺少依赖。请重新运行安装脚本。" & return & return & "日志：" & (item 1 of argv)) ¬
    as critical buttons {"好"} default button "好"
end run
APPLESCRIPT
  exit 1
fi

PDF_TO_MD_LOG_FILE="$LOG_FILE" /usr/bin/nohup /usr/bin/caffeinate -i "$PYTHON_BIN" \
  "$SCRIPT_DIR/pdf_to_md_batch.py" "$@" >>"$LOG_FILE" 2>&1 </dev/null &

/usr/bin/osascript - "$#" <<'APPLESCRIPT' >/dev/null 2>&1 || true
on run argv
  display dialog ((item 1 of argv) & " 个文件已开始 OCR 转换。" & return & "处理完成或失败时会再次提示。") ¬
    with title "PDF to Markdown" buttons {"好"} default button "好" giving up after 2
end run
APPLESCRIPT
