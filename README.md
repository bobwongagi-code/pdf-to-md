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
export PADDLEOCR_DOC_PARSING_TIMEOUT="120"
```

3. Run a quick check:

```bash
python scripts/smoke_test.py --skip-api-test
```

4. Convert a local PDF to Markdown:

```bash
python scripts/pdf_to_md.py "/absolute/path/to/document.pdf" --pretty
```

This writes:

- a same-name Markdown file beside the source PDF
- a JSON result file for debugging, with the saved path printed to stderr

## Common Commands

```bash
# Local PDF -> same-name Markdown file + saved JSON
python scripts/pdf_to_md.py "/path/file.pdf" --pretty

# Local PDF -> custom Markdown output path
python scripts/pdf_to_md.py "/path/file.pdf" --markdown-output "/path/file.md" --pretty

# Remote PDF URL -> saved JSON result
python scripts/vl_caller.py --file-url "https://example.com/file.pdf" --file-type 0 --pretty

# Local image -> saved JSON result
python scripts/vl_caller.py --file-path "/path/file.png" --file-type 1 --pretty

# Re-run without cache
python scripts/pdf_to_md.py "/path/file.pdf" --no-cache --pretty

# Show timing breakdown
python scripts/pdf_to_md.py "/path/file.pdf" --timing --pretty
```

## Behavior

- Local PDFs over 100 pages are automatically split and merged
- Repeat local-file runs can reuse cached results
- Raw JSON output is preserved for debugging
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
