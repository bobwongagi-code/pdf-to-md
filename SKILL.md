---
name: pdf-to-md
description: Convert PDFs and document images into Markdown and structured JSON with PaddleOCR Document Parsing.
---

# PDF to Markdown

Use this skill when the user wants a PDF or document image converted into Markdown, especially for:

- PDFs with tables, formulas, charts, or multi-column layout
- local PDFs where a same-name `.md` file should be written beside the source file
- cases where raw structured JSON should also be preserved for debugging

Use `python scripts/pdf_to_md.py` for the normal local-file flow.
Use `python scripts/vl_caller.py` for URL inputs or when you need lower-level flags.

## Install

```bash
pip install -r scripts/requirements.txt
```

Optional:

```bash
pip install -r scripts/requirements-optimize.txt
```

Before first real use:

```bash
python scripts/smoke_test.py --skip-api-test
```

## Rules

1. Use the provided scripts. Do not silently switch to a different parser.
2. If the API call fails, show the error and stop.
3. For local files, prefer the wrapper script that writes Markdown directly.

## Commands

Local file:

```bash
python scripts/pdf_to_md.py "/absolute/path/to/document.pdf" --pretty
```

Local file with explicit Markdown path:

```bash
python scripts/pdf_to_md.py "/absolute/path/to/document.pdf" --markdown-output "/absolute/path/to/document.md" --pretty
```

Remote URL:

```bash
python scripts/vl_caller.py --file-url "https://example.com/file.pdf" --file-type 0 --pretty
```

Scanned or rotated local file:

```bash
python scripts/pdf_to_md.py "/absolute/path/to/scan.pdf" --doc-unwarping --orientation-classify --pretty
```

Fresh parse without cache:

```bash
python scripts/pdf_to_md.py "/absolute/path/to/document.pdf" --no-cache --pretty
```

## Output

- `pdf_to_md.py` writes a same-name `.md` file beside the local source file by default
- `--markdown-output` writes Markdown to a custom path
- JSON results are still saved unless `--stdout` is used on `vl_caller.py`
- read the top-level `text` field when you need the Markdown content from saved JSON

## Errors

If config is missing, the error will look like:

```text
CONFIG_ERROR: PADDLEOCR_DOC_PARSING_API_URL not configured. Get your API at: https://paddleocr.com
```

Required environment variables:

- `PADDLEOCR_DOC_PARSING_API_URL`
- `PADDLEOCR_ACCESS_TOKEN`
- optional: `PADDLEOCR_DOC_PARSING_TIMEOUT`

Do not paste live credentials into tracked files.

## References

- Output schema: [`references/output_schema.md`](./references/output_schema.md)
- Example flow: [`examples/quickstart.md`](./examples/quickstart.md)
- Regression checklist: [`docs/regression-cases.md`](./docs/regression-cases.md)
