# Changelog

All notable changes to this repository should be documented here.

This project follows a simple keep-a-changelog style format.

## [Unreleased]

### Changed

- fixed Finder runtime interpreter selection and dependency preflight, preserved supported local tuning settings across reinstalls, and removed hardcoded batch chunk overrides
- bounded Markdown asset count, aggregate size and download time, and restricted reference rewriting to Markdown/HTML image destinations
- added runtime import-closure validation and an end-to-end CLI composition test
- hardened output publication with collision checks, atomic writes, stale-output protection and bounded cache pruning
- validated complete OCR page coverage before accepting or caching a result, including duplicate and empty-page checks
- added HTTPS endpoint validation, Keychain-safe token input, idempotent retries, Retry-After handling, cancellation and whole-file deadlines
- materialized Markdown image resources into a sibling `.assets` directory, including Finder batch output staging
- made Finder status updates observable before expensive hashing and reported refresh failures instead of claiming installation success
- made raw provider JSON opt-in and documented the normalized chunked result schema
- added a single runtime version source, Finder runtime manifest hashes and CI metadata verification
- added request/source size guards, stricter cache coverage validation, ordered page checks and blank-page Markdown markers
- made Finder runtime, workflow and local config publication rollback-safe as one file-backed install transaction
- made Markdown asset downloads streamed and deduplicated, and bounded optimizer target sizes
- default large local PDF OCR chunking now uses smaller 20-page chunks and one worker for API stability
- added `--chunk-pages` and `--chunk-workers` controls for local PDF OCR chunking
- Markdown output is no longer written when parsing fails or extracted text is empty
- documented PaddleOCR as the primary conversion path and restricted `pypdf` fallback to explicit user-confirmed use after three whole-file OCR failures
- documented large-PDF OCR retry rules so successful chunk cache is reused instead of bypassed
- added macOS Keychain fallback for `PADDLEOCR_ACCESS_TOKEN` so tokens do not need to live in shell config
- added a one-time macOS Finder Quick Action installer and background batch runner for right-click PDF conversion

## [2.0.9] - 2026-04-25

### Added

- `scripts/pdf_to_md.py` as a thin local-file wrapper for the common PDF-to-Markdown flow
- `agents/openai.yaml` with display metadata, default prompt, icons, and brand color
- lightweight SVG icons under `assets/` for UI presentation

### Changed

- renamed the skill metadata and package slug consistently to `pdf-to-md`
- added first-class Markdown file output support to `scripts/vl_caller.py`
- simplified `README.md` and `SKILL.md` around the default local-file workflow
- updated quickstart, schema notes, and smoke-test examples to match the new entrypoints
- removed stale `openclaw` and old `paddleocr-doc-parsing` naming leftovers from docs and examples

## [2.0.8] - 2026-04-06

### Added

- GitHub-ready `README.md`
- `CHANGELOG.md`
- `CONTRIBUTING.md`
- `examples/quickstart.md`
- `--version` support in `scripts/vl_caller.py`
- timing output support
- `--doc-unwarping` and `--orientation-classify` flags
- chunk-level cache reuse for large local PDFs
- version metadata in `_meta.json`
- repository `.gitignore`

### Changed

- strengthened local-file validation before API requests
- improved cache key correctness for runtime parse options
- normalized file type handling for cache keys
- added cache TTL support
- made cache/result writes atomic
- improved chunk error context with page ranges
- made local PDF splitting safer before chunk parsing
- reused HTTP connections more effectively
- improved large-PDF handling and retry behavior
- improved `smoke_test.py` and configuration visibility
- made `optimize_file.py` explicitly explain that PDF optimization is not supported

### Fixed

- stale or misleading cache reuse in some option/file-type combinations
- silent loss of warning signals when logging was not configured
- poor diagnostics for large-file chunk failures
- incorrect default SSH key use during repo publishing workflow by documenting cleaner repo usage paths

## [2.0.7] - 2026-03-28

### Added

- initial stable public packaging of the skill repository
