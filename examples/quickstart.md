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

## 4. Parse a PDF

```bash
python scripts/vl_caller.py \
  --file-path "/absolute/path/to/document.pdf" \
  --file-type 0 \
  --pretty
```

Typical stderr output:

```text
Result saved to: /tmp/paddleocr/doc-parsing/results/result_20260406_120000_abc123.json
```

## 5. Read the Markdown Text

Open the saved JSON and read the top-level `text` field.

Minimal example:

```python
import json
from pathlib import Path

result_path = Path("/tmp/paddleocr/doc-parsing/results/result_20260406_120000_abc123.json")
data = json.loads(result_path.read_text(encoding="utf-8"))
markdown_text = data["text"]
print(markdown_text[:1000])
```

## 6. Optional: Save as `.md`

```python
import json
from pathlib import Path

pdf_path = Path("/absolute/path/to/document.pdf")
json_path = Path("/tmp/paddleocr/doc-parsing/results/result_20260406_120000_abc123.json")

data = json.loads(json_path.read_text(encoding="utf-8"))
pdf_path.with_suffix(".md").write_text(data["text"] + "\n", encoding="utf-8")
```

## Tips

- Use `--timing` when you want a phase-by-phase runtime breakdown
- Use `--no-cache` when you need a fresh API result
- Use `--doc-unwarping` and `--orientation-classify` for scanned or rotated inputs
- For very large PDFs, prefer the built-in chunking flow or `scripts/split_pdf.py`
