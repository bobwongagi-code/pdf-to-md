# Regression Cases

Use this file as the lightweight regression checklist for real-world parsing behavior.

The goal is simple:

- keep successful cases successful
- keep recovered failure paths recoverable
- notice when performance or stability regresses

## How to Use This File

When making changes to parsing behavior, caching, large-file handling, or retry logic:

1. Pick at least one relevant case from this list.
2. Re-run the case after the change.
3. Record whether behavior improved, stayed stable, or regressed.

## Current Cases

| Case ID | File Type | Scenario | Expected Behavior | Status |
|---|---|---|---|---|
| `small-pdf-basic` | local PDF | small normal PDF under 100 pages | direct parse succeeds without split | baseline defined |
| `normal-pdf-basic` | local PDF | normal multi-page PDF under 100 pages | direct parse succeeds and returns usable `text` | baseline defined |
| `large-pdf-auto-split` | local PDF | PDF over 100 pages | auto-split path succeeds or fails with actionable chunk context | baseline defined |
| `large-pdf-repeat-cache` | local PDF | rerun same large PDF | repeat run reuses full cache or chunk cache where applicable | baseline defined |
| `scan-orientation` | local PDF/image | scanned or rotated input | optional preprocessing flags produce isolated cache keys and stable output | baseline defined |

## Detailed Case: `openclaw-large-pdf-recovery`

- Input file: `OpenClaw橙皮书-从入门到精通-v1.4.0.pdf`
- Location used during investigation:
  `/Users/wangbo5/Documents/AI资料学习/OpenClaw/OpenClaw橙皮书-从入门到精通-v1.4.0.pdf`
- File size: about `8.9 MB`
- Page count: `114`

### Why It Matters

This case is the best current real-world benchmark for large-file stability because it exercised:

- page counting
- automatic split behavior
- chunk parsing
- timeout handling
- manual recovery by smaller chunks
- final merged Markdown output

### Observed Behavior

Initial default behavior did not fully succeed on the first pass.

Observed failure and recovery path:

1. default split path used `1-100` and `101-114`
2. an early recovery attempt hit page import failure
3. after split/parse flow hardening, chunk `1/2` then timed out at the API layer
4. manual smaller chunks `1-40`, `41-80`, and `81-114` succeeded
5. outputs were merged back into a final Markdown file

### Expected Ongoing Outcome

Future changes should preserve at least this recovery quality:

- failing chunk should be identifiable
- recovery should not require ad hoc code edits
- merged output should remain ordered and usable

### Evidence

See the external case write-up:

- `/Users/wangbo5/Documents/New project/docs/paddleocr-case-openclaw-large-pdf-2026-04-05.md`

## Notes to Maintainers

- Add new entries when a real file teaches us something important.
- Prefer concrete files and concrete failure modes over vague summaries.
- If a case includes sensitive material, record only the behavior pattern and not the private content.
