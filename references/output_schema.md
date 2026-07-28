# PDF to Markdown Output Schema

This document defines the output envelope returned by `vl_caller.py`.

The normal local Markdown flow does not save provider JSON. Use `--output` or `--keep-raw` when you explicitly need the JSON envelope; use `--stdout` to print it directly.

## Output Envelope

`vl_caller.py` wraps provider response in a stable structure:

```json
{
  "ok": true,
  "text": "Extracted text from all pages",
  "coverage": {
    "expected_pages": 1,
    "returned_pages": 1,
    "missing_pages": [],
    "empty_pages": [],
    "duplicate_pages": [],
    "page_ids": [],
    "partial": false,
    "complete": true
  },
  "assets": {},
  "result": { ... },
  "error": null
}
```

On error:

```json
{
  "ok": false,
  "text": "",
  "result": null,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable message"
  }
}
```

## Error Codes

| Code | Description |
|------|-------------|
| `INPUT_ERROR` | Invalid input (missing file, unsupported format) |
| `CONFIG_ERROR` | API not configured |
| `API_ERROR` | API call failed (auth, timeout, service error, or invalid response schema) |

## Result Notes

For a direct request, `result` contains the raw provider output. For an automatically split PDF, `result.type` is `chunked_ocr` and contains one record per source page range plus a normalized `merged` section. Raw provider responses are retained only in explicitly requested JSON output, not in the resumable cache.

## Raw Result Example

```json
{
  "logId": "request-uuid",
  "errorCode": 0,
  "errorMsg": "Success",
  "result": {
    "layoutParsingResults": [
      {
        "prunedResult": { ... },  // layout elements with position/content/confidence information
        "markdown": {
          "text": "Full page content in markdown/HTML format",
          "images": {
            "imgs/filename.jpg": "https://..."
          },
          "...": "other model-specific fields"
        }
      }
    ]
  }
}
```

## Important Fields

- `result[n].prunedResult`  
  Structured parsing data for page `n` (layout elements, locations, content, confidence, and related metadata).

- `result[n].markdown`  
  Rendered output for page `n`.

- `result[n].markdown.text`  
  Full page markdown text.

## Text Extraction

`vl_caller.py` extracts top-level `text` from `result.layoutParsingResults[n].markdown.text` and joins pages with `\n\n`.

## Command Examples

```bash
# Parse document from URL (prints JSON to stdout when --stdout is used)
python scripts/vl_caller.py --file-url "URL" --pretty

# Parse local file and write Markdown beside it
python scripts/vl_caller.py --file-path "doc.pdf" --pretty

# Keep raw provider JSON explicitly
python scripts/vl_caller.py --file-path "doc.pdf" --keep-raw --pretty

# Save result to a custom file path
python scripts/vl_caller.py --file-url "URL" --output "./result.json" --pretty

# Print JSON to stdout without saving a file
python scripts/vl_caller.py --file-url "URL" --stdout --pretty
```
