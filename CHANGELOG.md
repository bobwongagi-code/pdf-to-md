# Changelog

All notable changes to this repository should be documented here.

This project follows a simple keep-a-changelog style format.

## [Unreleased]

- added `LICENSE` with Apache-2.0
- updated `README.md` to point to the repository license
- added repository badges for version, Python support, and license
- added GitHub issue templates and pull request template
- added a lightweight GitHub Actions workflow for version and smoke-test checks

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
