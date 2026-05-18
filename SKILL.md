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

On macOS, prefer storing the access token in Keychain instead of shell config:

```bash
security add-generic-password -s "pdf-to-md.paddleocr" -a "PADDLEOCR_ACCESS_TOKEN" -w "your-token" -U
```

## Rules

1. Use the provided scripts. Do not silently switch to a different parser.
2. If the API call fails, show the error and stop.
3. For local files, prefer the wrapper script that writes Markdown directly.
4. Treat PaddleOCR as the primary path. Do not use `pypdf` during normal conversion.
5. Do not report success unless a non-empty Markdown file was written.
6. `pypdf` is only allowed after three whole-file OCR attempts have failed, and only after asking the user for confirmation first.
7. Count an OCR attempt at the PDF job level: one command run for one source file counts once, even if the script splits that PDF into many chunks internally.
8. For large PDF OCR retries, keep cache enabled and keep the same `--chunk-pages` first, so successful chunks are reused and only failed chunks are retried.
9. Do not store live API tokens in tracked files. Prefer `PADDLEOCR_ACCESS_TOKEN` from the environment or macOS Keychain fallback.

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

Use `--no-cache` only when you suspect cached content is wrong or stale. Do not use it for normal large-PDF OCR retries.

Large PDF with explicit stable chunking:

```bash
python scripts/pdf_to_md.py "/absolute/path/to/report.pdf" --chunk-pages 20 --chunk-workers 1 --pretty
```

## Output

- `pdf_to_md.py` writes a same-name `.md` file beside the local source file by default
- `--markdown-output` writes Markdown to a custom path
- failed or empty parses do not overwrite Markdown output
- JSON results are still saved unless `--stdout` is used on `vl_caller.py`
- read the top-level `text` field when you need the Markdown content from saved JSON

## Errors

If OCR fails:

- retry OCR up to three whole-file attempts, preferably with smaller chunks for large PDFs
- do not count individual chunk failures as separate OCR attempts; chunking is an implementation detail of one file-level attempt
- first retry should usually rerun the same command without `--no-cache`, preserving the same `--chunk-pages` so cached successful chunks are reused
- only shrink `--chunk-pages` after the same page range fails again; changing chunk size prevents reuse of earlier chunk cache for those different page ranges
- if all three OCR attempts fail, stop and report the OCR error
- ask the user before using `pypdf` fallback
- clearly label any `pypdf` output as fallback quality if the user confirms
- do not use `pypdf` for convenience, speed, or normal text PDFs

If config is missing, the error will look like:

```text
CONFIG_ERROR: PADDLEOCR_DOC_PARSING_API_URL not configured. Get your API at: https://paddleocr.com
```

Required environment variables:

- `PADDLEOCR_DOC_PARSING_API_URL`
- `PADDLEOCR_ACCESS_TOKEN` or macOS Keychain item `service=pdf-to-md.paddleocr`, `account=PADDLEOCR_ACCESS_TOKEN`
- optional: `PADDLEOCR_DOC_PARSING_TIMEOUT`

Do not paste live credentials into tracked files.

## References

- Output schema: [`references/output_schema.md`](./references/output_schema.md)
- Example flow: [`examples/quickstart.md`](./examples/quickstart.md)
- Regression checklist: [`docs/regression-cases.md`](./docs/regression-cases.md)
