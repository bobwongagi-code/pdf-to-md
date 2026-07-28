# Quickstart Example

This example shows the shortest reliable path from a local PDF to usable Markdown text.

## 1. Install Dependencies

```bash
pip install -r scripts/requirements.txt
```

## 2. Set Environment Variables

```bash
export PADDLEOCR_DOC_PARSING_API_URL="https://your-endpoint/layout-parsing"
export PADDLEOCR_ACCESS_TOKEN="your-token"
export PADDLEOCR_DOC_PARSING_TIMEOUT="120"
```

## 3. Run a Quick Check

```bash
python scripts/smoke_test.py --skip-api-test
```

## 4. Parse a PDF and write Markdown

```bash
python scripts/pdf_to_md.py "/absolute/path/to/document.pdf" --pretty
```

Typical stderr output:

```text
Markdown saved to: /absolute/path/to/document.md
```

## 5. Read the Markdown Text

Open `/absolute/path/to/document.md` directly.

Raw provider JSON is not retained by the normal Markdown flow. Use `--keep-raw` or an explicit `--output` path only when you need to inspect the envelope and its top-level `text` field.

```bash
python scripts/pdf_to_md.py "/absolute/path/to/document.pdf" --output "/tmp/document.json" --pretty
```

```python
import json
from pathlib import Path

result_path = Path("/tmp/paddleocr/doc-parsing/results/result_20260406_120000_abc123.json")
data = json.loads(result_path.read_text(encoding="utf-8"))
markdown_text = data["text"]
print(markdown_text[:1000])
```

## Tips

- Use `--timing` when you want a phase-by-phase runtime breakdown
- Use `--no-cache` when you need a fresh API result
- Use `--doc-unwarping` and `--orientation-classify` for scanned or rotated inputs
- For very large PDFs, prefer the built-in chunking flow or `scripts/split_pdf.py`
