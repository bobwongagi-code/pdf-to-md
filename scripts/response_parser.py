# Copyright (c) 2025 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Validation and extraction of PaddleOCR document responses."""

from typing import Optional

from contracts import Coverage, ParseResult


def _extract_text(result: object) -> str:
    """Extract Markdown text from the provider page list."""
    if not isinstance(result, dict):
        raise ValueError(
            "Invalid response schema: top-level response must be an object"
        )
    raw_result = result.get("result")
    if not isinstance(raw_result, dict):
        raise ValueError("Invalid response schema: missing result object")
    pages = raw_result.get("layoutParsingResults")
    if not isinstance(pages, list):
        raise ValueError(
            "Invalid response schema: result.layoutParsingResults must be an array"
        )
    if not pages:
        raise ValueError("Invalid response schema: result.layoutParsingResults is empty")

    texts = []
    for index, page in enumerate(pages):
        if not isinstance(page, dict):
            raise ValueError(
                f"Invalid response schema: result.layoutParsingResults[{index}] "
                "must be an object"
            )
        markdown = page.get("markdown")
        if not isinstance(markdown, dict):
            raise ValueError(
                f"Invalid response schema: result.layoutParsingResults[{index}]."
                "markdown must be an object"
            )
        text = markdown.get("text")
        if not isinstance(text, str):
            raise ValueError(
                f"Invalid response schema: result.layoutParsingResults[{index}]."
                "markdown.text must be a string"
            )
        if text.strip():
            texts.append(text)
        elif _is_explicit_blank_page(page):
            texts.append(f"<!-- OCR detected blank page {index + 1} -->")

    extracted = "\n\n".join(texts)
    if not extracted.strip():
        raise ValueError("OCR response contains only empty Markdown text")
    return extracted


def _page_identifier(page: dict) -> Optional[int]:
    for key in ("pageIndex", "page_index", "pageNo", "pageNumber", "page_id"):
        value = page.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _is_explicit_blank_page(page: dict) -> bool:
    for key in ("isBlank", "is_blank", "blank", "isEmpty", "empty"):
        if page.get(key) is True:
            return True
    markdown = page.get("markdown")
    if isinstance(markdown, dict):
        for key in ("isBlank", "is_blank", "blank", "isEmpty", "empty"):
            if markdown.get(key) is True:
                return True
    return False


def _extract_markdown_assets(result: dict) -> dict[str, str]:
    assets: dict[str, str] = {}
    raw_result = result.get("result") if isinstance(result, dict) else None
    pages = (
        raw_result.get("layoutParsingResults")
        if isinstance(raw_result, dict)
        else None
    )
    if not isinstance(pages, list):
        return assets
    for page in pages:
        if not isinstance(page, dict):
            continue
        markdown = page.get("markdown")
        if not isinstance(markdown, dict):
            continue
        images = markdown.get("images")
        if not isinstance(images, dict):
            continue
        for name, url in images.items():
            if isinstance(name, str) and isinstance(url, str) and name and url:
                assets[name] = url
    return assets


def _validate_page_coverage(
    result: dict,
    expected_pages: Optional[int],
) -> Coverage:
    raw_result = result.get("result")
    pages = (
        raw_result.get("layoutParsingResults")
        if isinstance(raw_result, dict)
        else None
    )
    if not isinstance(pages, list):
        raise ValueError("Invalid response schema: missing page list")
    if expected_pages is not None and len(pages) != expected_pages:
        raise ValueError(
            f"OCR returned {len(pages)} page(s), expected {expected_pages}; "
            "refusing partial result"
        )

    empty_pages = []
    page_ids = []
    for index, page in enumerate(pages, start=1):
        if not isinstance(page, dict):
            raise ValueError(f"OCR page {index} is not an object")
        markdown = page.get("markdown")
        text = markdown.get("text") if isinstance(markdown, dict) else None
        if not isinstance(text, str):
            raise ValueError(f"OCR page {index} has no Markdown text")
        if not text.strip():
            if not _is_explicit_blank_page(page):
                raise ValueError(
                    f"OCR page {index} has empty Markdown without explicit "
                    "blank-page evidence"
                )
            empty_pages.append(index)
        page_id = _page_identifier(page)
        if page_id is not None:
            page_ids.append(page_id)

    if page_ids:
        if len(page_ids) != len(set(page_ids)):
            raise ValueError("OCR response contains duplicate page identifiers")
        expected_zero_based = set(range(len(pages)))
        expected_one_based = set(range(1, len(pages) + 1))
        page_id_set = set(page_ids)
        if page_id_set not in (expected_zero_based, expected_one_based):
            raise ValueError("OCR response page identifiers are not contiguous")
        expected_order = (
            list(range(len(pages)))
            if page_id_set == expected_zero_based
            else list(range(1, len(pages) + 1))
        )
        if page_ids != expected_order:
            raise ValueError("OCR response page identifiers are out of order")

    return {
        "expected_pages": expected_pages if expected_pages is not None else len(pages),
        "returned_pages": len(pages),
        "missing_pages": [],
        "empty_pages": empty_pages,
        "duplicate_pages": [],
        "page_ids": page_ids,
        "partial": False,
        "complete": True,
    }


def error_result(code: str, message: str) -> ParseResult:
    """Create the common structured parser error envelope."""
    return {
        "ok": False,
        "text": "",
        "result": None,
        "error": {"code": code, "message": message},
    }


_error = error_result
