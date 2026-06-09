# PDF to Markdown

[![ci](https://github.com/bobwongagi-code/pdf-to-md/actions/workflows/ci.yml/badge.svg)](https://github.com/bobwongagi-code/pdf-to-md/actions/workflows/ci.yml)
[![version](https://img.shields.io/badge/version-2.0.9-blue)](./_meta.json)
[![python](https://img.shields.io/badge/python-3.9%2B-3776AB)](./scripts/requirements.txt)
[![license](https://img.shields.io/badge/license-Apache%202.0-green)](./LICENSE)

Convert local PDFs and document images into Markdown and structured JSON with PaddleOCR Document Parsing.

## Quick Start

1. Install dependencies:

```bash
pip install -r scripts/requirements.txt
```

2. Configure the endpoint:

```bash
export PADDLEOCR_DOC_PARSING_API_URL="https://your-endpoint/layout-parsing"
export PADDLEOCR_ACCESS_TOKEN="your-token"
export PADDLEOCR_DOC_PARSING_MODEL="PaddleOCR-VL-1.6"
export PADDLEOCR_DOC_PARSING_TIMEOUT="120"
```

On macOS, prefer storing the access token in Keychain instead of shell config:

```bash
export PADDLEOCR_DOC_PARSING_API_URL="https://your-endpoint/layout-parsing"
export PADDLEOCR_DOC_PARSING_MODEL="PaddleOCR-VL-1.6"
security add-generic-password \
  -s "pdf-to-md.paddleocr" \
  -a "PADDLEOCR_ACCESS_TOKEN" \
  -w "your-token" \
  -U
```

3. Run a quick check:

```bash
python scripts/smoke_test.py --skip-api-test
```

4. Convert a local PDF or document image to Markdown:

```bash
python scripts/pdf_to_md.py "/absolute/path/to/document.pdf" --pretty
python scripts/pdf_to_md.py "/absolute/path/to/scan.png" --pretty
```

This writes:

- a same-name Markdown file beside the source PDF or image
- a JSON result file for debugging, with the saved path printed to stderr

## Finder Quick Action

On macOS, install the Finder right-click action once:

```bash
python scripts/install_quick_action.py --store-env-token
```

The installer:

- installs `转为 Markdown (OCR)` in Finder Quick Actions
- writes non-secret endpoint settings to `~/.config/pdf-to-md/config.env`
- stores the current `PADDLEOCR_ACCESS_TOKEN` in Keychain when `--store-env-token` is used

After installation, select one or more PDF or image files in Finder and choose `Quick Actions > 转为 Markdown (OCR)`. Conversion runs in the background, immediately confirms that the task started, writes Markdown beside each source file, preserves chunk cache for PDF resume, and sends completion notifications. Failed conversions show a foreground error with a `查看日志` button. Logs and task status JSON are written under `~/Library/Logs/pdf-to-md/`.

The first time after installation, open `Quick Actions > Customize...` and enable `转为 Markdown (OCR)` in Finder extensions. Re-run the installer only if the Python environment, configuration, or skill implementation changes.

## Common Commands

```bash
# Local PDF -> same-name Markdown file + saved JSON
python scripts/pdf_to_md.py "/path/file.pdf" --pretty

# Local image -> same-name Markdown file + saved JSON
python scripts/pdf_to_md.py "/path/file.png" --pretty

# Local PDF -> custom Markdown output path
python scripts/pdf_to_md.py "/path/file.pdf" --markdown-output "/path/file.md" --pretty

# Remote PDF URL -> saved JSON result
python scripts/vl_caller.py --file-url "https://example.com/file.pdf" --file-type 0 --pretty

# Local image -> saved JSON result only
python scripts/vl_caller.py --file-path "/path/file.png" --file-type 1 --pretty

# Re-run without cache
python scripts/pdf_to_md.py "/path/file.pdf" --no-cache --pretty

# Show timing breakdown
python scripts/pdf_to_md.py "/path/file.pdf" --timing --pretty

# Tune large-PDF OCR if the default is too slow or too conservative
python scripts/pdf_to_md.py "/path/file.pdf" --chunk-pages 25 --chunk-workers 1 --pretty
```

## Behavior

- PaddleOCR Document Parsing is the primary conversion path
- PaddleOCR official API requests default to `model=PaddleOCR-VL-1.6`
- `PADDLEOCR_ACCESS_TOKEN` is read from the environment first, then macOS Keychain
- `PADDLEOCR_DOC_PARSING_API_URL` is read from the environment first, then `~/.config/pdf-to-md/config.env` for Finder execution
- `PADDLEOCR_DOC_PARSING_MODEL` can override the official API model name
- Local images use PaddleOCR image parsing and write same-name Markdown by default
- Local PDFs over 20 pages are automatically split and merged
- Large local PDFs default to 20-page chunks and one worker for API stability
- Increase `--chunk-pages` or `--chunk-workers` only when you know the endpoint can handle the load
- Failed or empty parses do not overwrite Markdown output
- Repeat local-file runs can reuse cached results
- For large PDF OCR failures, rerun with cache enabled and the same `--chunk-pages` first so successful chunks are reused
- Use `--no-cache` only when cached content is suspected to be wrong or stale
- Raw JSON output is preserved for debugging
- `pypdf` text extraction is not a normal conversion path
- use `pypdf` only after three whole-file OCR attempts fail, and only after explicit user confirmation
- whole-file attempt means one command run for one source PDF; internally split chunks do not count as separate attempts
- any `pypdf` output should be labeled as fallback quality because text-layer extraction can damage sentence flow and meaning
- `optimize_file.py` only applies to image inputs, not PDFs

## Validation

```bash
python scripts/vl_caller.py --version
python -m unittest discover -s tests -v
python scripts/smoke_test.py --skip-api-test
```

## More Files

- Skill instructions: [`SKILL.md`](./SKILL.md)
- Example flow: [`examples/quickstart.md`](./examples/quickstart.md)
- Output schema: [`references/output_schema.md`](./references/output_schema.md)
- Regression checklist: [`docs/regression-cases.md`](./docs/regression-cases.md)
- Contribution guide: [`CONTRIBUTING.md`](./CONTRIBUTING.md)
- Security policy: [`SECURITY.md`](./SECURITY.md)

## License

Licensed under the Apache License 2.0. See [`LICENSE`](./LICENSE).
