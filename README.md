# PaddleOCR PDF to Markdown Skill

Convert PDFs and document images into Markdown and structured JSON with PaddleOCR Document Parsing.

This repository packages a Codex/OpenClaw skill plus the supporting Python scripts used to call the PaddleOCR Document Parsing API in a stable, production-friendly way.

## Quick Start

1. Install dependencies:

```bash
pip install -r scripts/requirements.txt
```

2. Configure your endpoint:

```bash
export PADDLEOCR_DOC_PARSING_API_URL="https://your-endpoint/layout-parsing"
export PADDLEOCR_ACCESS_TOKEN="your-token"
export PADDLEOCR_DOC_PARSING_TIMEOUT="120"
```

3. Run a quick health check:

```bash
python scripts/smoke_test.py --skip-api-test
```

4. Convert a local PDF:

```bash
python scripts/vl_caller.py \
  --file-path "/absolute/path/to/document.pdf" \
  --file-type 0 \
  --pretty
```

5. Read the saved JSON path from stderr and use the top-level `text` field as the Markdown output.

## What It Does

- Converts local PDFs and document images to Markdown
- Preserves document structure better than plain OCR
- Saves raw JSON results for inspection and debugging
- Reuses cache for repeated local-file runs
- Retries transient API failures with bounded backoff
- Splits large local PDFs into smaller chunks and merges results back
- Supports optional document unwarping and orientation correction

## Repository Layout

```text
.
├── README.md
├── SKILL.md
├── _meta.json
├── references/
│   └── output_schema.md
└── scripts/
    ├── lib.py
    ├── optimize_file.py
    ├── requirements.txt
    ├── requirements-optimize.txt
    ├── smoke_test.py
    ├── split_pdf.py
    └── vl_caller.py
```

## Requirements

- Python 3.9+
- A PaddleOCR Document Parsing endpoint
- A PaddleOCR access token

Install dependencies:

```bash
pip install -r scripts/requirements.txt
```

Optional utilities for image optimization and PDF page extraction:

```bash
pip install -r scripts/requirements-optimize.txt
```

Recommended for most users:

- `scripts/requirements.txt` is enough for normal parsing
- `scripts/requirements-optimize.txt` is only needed if you want image optimization or local PDF page extraction helpers

## Configuration

Set these environment variables:

```bash
export PADDLEOCR_DOC_PARSING_API_URL="https://your-endpoint/layout-parsing"
export PADDLEOCR_ACCESS_TOKEN="your-token"
export PADDLEOCR_DOC_PARSING_TIMEOUT="120"
```

Run a quick health check before first use:

```bash
python scripts/smoke_test.py --skip-api-test
```

Run a real API smoke test:

```bash
python scripts/smoke_test.py
```

## Command Cheat Sheet

Most common commands:

```bash
# Local PDF -> saved JSON result
python scripts/vl_caller.py --file-path "/path/file.pdf" --file-type 0 --pretty

# Local image -> saved JSON result
python scripts/vl_caller.py --file-path "/path/file.png" --file-type 1 --pretty

# Remote PDF URL -> saved JSON result
python scripts/vl_caller.py --file-url "https://example.com/file.pdf" --file-type 0 --pretty

# Print JSON to stdout
python scripts/vl_caller.py --file-path "/path/file.pdf" --file-type 0 --stdout --pretty

# Skip cache
python scripts/vl_caller.py --file-path "/path/file.pdf" --file-type 0 --pretty --no-cache

# Enable timing output
python scripts/vl_caller.py --file-path "/path/file.pdf" --file-type 0 --pretty --timing

# Scanned/rotated documents
python scripts/vl_caller.py --file-path "/path/file.pdf" --file-type 0 --doc-unwarping --orientation-classify --pretty
```

## Basic Usage

Convert a local PDF:

```bash
python scripts/vl_caller.py \
  --file-path "/absolute/path/to/document.pdf" \
  --file-type 0 \
  --pretty
```

Convert a local image:

```bash
python scripts/vl_caller.py \
  --file-path "/absolute/path/to/document.jpg" \
  --file-type 1 \
  --pretty
```

Convert a remote file by URL:

```bash
python scripts/vl_caller.py \
  --file-url "https://example.com/file.pdf" \
  --file-type 0 \
  --pretty
```

Print JSON to stdout instead of saving a result file:

```bash
python scripts/vl_caller.py \
  --file-path "/absolute/path/to/document.pdf" \
  --stdout \
  --pretty
```

Enable preprocessing for scanned or rotated documents:

```bash
python scripts/vl_caller.py \
  --file-path "/absolute/path/to/scan.pdf" \
  --file-type 0 \
  --doc-unwarping \
  --orientation-classify \
  --pretty
```

Show version:

```bash
python scripts/vl_caller.py --version
```

## Output

By default, results are saved under the system temp directory:

```text
<temp>/paddleocr/doc-parsing/results/result_<timestamp>_<id>.json
```

The saved JSON looks like this:

```json
{
  "ok": true,
  "text": "Full extracted markdown text",
  "result": { "...": "raw provider payload" },
  "error": null
}
```

In most cases:

- Use `text` for the Markdown output you want
- Use `result` when you need raw provider details for debugging or deeper extraction

If you want a standalone `.md` file beside the original PDF, a simple workflow is:

1. Run `vl_caller.py`
2. Open the saved JSON file
3. Copy the top-level `text` field into a same-name `.md` file

This repo keeps the parsing layer and the final Markdown file creation loosely coupled on purpose. It makes debugging much easier because the raw provider result is always preserved.

## Stability and Performance Defaults

This repo has already been tuned around two priorities: stability first, then speed.

Current behavior includes:

- Local input validation before API calls
- Full-result cache for repeated local-file runs
- Chunk-level cache for large local PDFs
- Bounded retries for transient API/network failures
- Automatic splitting for local PDFs over 100 pages
- Atomic cache/result writes to reduce corruption risk
- Timing output support for profiling

Enable timing breakdowns:

```bash
python scripts/vl_caller.py \
  --file-path "/absolute/path/to/document.pdf" \
  --file-type 0 \
  --pretty \
  --timing
```

Disable cache for a fresh parse:

```bash
python scripts/vl_caller.py \
  --file-path "/absolute/path/to/document.pdf" \
  --file-type 0 \
  --pretty \
  --no-cache
```

## Large PDF Notes

- Local PDFs over 100 pages are automatically chunked and merged
- Repeated large-file runs can reuse chunk cache
- If a very large PDF times out, smaller manual chunking may still be the fastest recovery path

Split a PDF manually:

```bash
python scripts/split_pdf.py \
  --input "/absolute/path/to/document.pdf" \
  --output "/absolute/path/to/chunk.pdf" \
  --pages "1-40"
```

Important: `optimize_file.py` only optimizes image inputs. It does not optimize PDFs. For large PDFs, prefer direct parsing, `--file-url`, or `split_pdf.py`.

## Troubleshooting

Missing API config:

```text
CONFIG_ERROR: PADDLEOCR_DOC_PARSING_API_URL not configured. Get your API at: https://paddleocr.com
```

What to check:

- `PADDLEOCR_DOC_PARSING_API_URL` is set
- `PADDLEOCR_ACCESS_TOKEN` is set
- The token matches the endpoint
- The endpoint supports the input type you are sending

Timeouts on large PDFs:

- Retry with `--timing` to confirm where time is spent
- Try smaller manual PDF chunks
- Consider using a remote file URL instead of local upload

Unexpected repeated failures:

- Run `python scripts/smoke_test.py`
- Retry once with `--no-cache`
- Inspect the saved JSON file and the reported error message

## Skill Context

This repository is designed to be used as a skill inside Codex/OpenClaw environments, but the scripts are also usable directly from the command line.

- Skill definition: [`SKILL.md`](./SKILL.md)
- Output schema notes: [`references/output_schema.md`](./references/output_schema.md)
- Example workflow: [`examples/quickstart.md`](./examples/quickstart.md)
- Contribution guide: [`CONTRIBUTING.md`](./CONTRIBUTING.md)
- Change history: [`CHANGELOG.md`](./CHANGELOG.md)

## License

Licensed under the Apache License 2.0. See [`LICENSE`](./LICENSE).
