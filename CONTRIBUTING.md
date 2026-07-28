# Contributing

Thanks for contributing.

The goal of this repository is practical reliability: keep the parsing path stable, keep the behavior explicit, and avoid changes that make debugging harder.

## Principles

- Prefer simple, maintainable changes
- Optimize for stability first, then speed
- Keep APIs and CLI behavior explicit
- Preserve raw debugging information only when the caller explicitly requests it
- Avoid heavy abstractions for small improvements

## Local Setup

Install the main dependencies:

```bash
pip install -r scripts/requirements.txt
```

Optional helper dependencies:

```bash
pip install -r scripts/requirements-optimize.txt
```

CI uses `scripts/requirements-lock.txt` to pin the complete direct and
transitive dependency set.

Set the required environment variables:

```bash
export PADDLEOCR_DOC_PARSING_API_URL="https://your-endpoint/layout-parsing"
export PADDLEOCR_ACCESS_TOKEN="your-token"
export PADDLEOCR_DOC_PARSING_TIMEOUT="120"
```

## Before Opening a Change

Please keep changes focused.

Good examples:

- improve retry behavior
- improve cache correctness
- improve large-PDF recovery
- improve docs or diagnostics

Less helpful examples:

- broad refactors without a runtime benefit
- dependency churn without a clear need
- behavior changes without updating docs

## Validation

For most changes, run:

```bash
python scripts/vl_caller.py --version
python -m unittest discover -s tests -v
python scripts/smoke_test.py --skip-api-test
```

If your change affects real parsing behavior, also run:

```bash
python scripts/smoke_test.py
```

If your change affects large-file handling, test at least one large local PDF path or one manual `split_pdf.py` workflow.

## Documentation Expectations

Update docs when behavior changes.

At minimum, keep these in sync:

- `README.md`
- `SKILL.md`
- `CHANGELOG.md`
- `SECURITY.md` when credential handling guidance changes
- `docs/regression-cases.md` when a new real-world benchmark case matters

Examples:

- new CLI flag
- changed cache behavior
- changed retry policy
- changed large-PDF handling

## Pull Request Guidance

Please include:

- what changed
- why it changed
- how you validated it
- any remaining risk or known limitation

Small, well-scoped pull requests are preferred.

## Notes for Skill Maintainers

- `README.md` is for GitHub and direct repository users
- `SKILL.md` is for skill-driven agent environments
- `SECURITY.md` documents secret-handling and disclosure expectations
- `docs/regression-cases.md` tracks real-world regression benchmarks
- `references/output_schema.md` documents output structure
- `scripts/vl_caller.py` is the main entry point

Implementation boundaries:

- cli.py owns CLI orchestration; pipeline.py owns PDF chunking and merge behavior
- ocr_client.py, config.py, and response_parser.py are the OCR client layers
- cache_store.py owns resumable cache state; artifacts.py owns Markdown, JSON,
  and image artifact output
- Finder runtime changes must update RUNTIME_FILES in
  scripts/install_quick_action.py

When in doubt, keep the default path boring and reliable.
