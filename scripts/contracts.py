"""Shared structural contracts for parser, cache, and chunk results."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class ErrorInfo(TypedDict, total=False):
    code: str
    message: str


class Coverage(TypedDict, total=False):
    expected_pages: Optional[int]
    returned_pages: int
    missing_pages: List[int]
    empty_pages: List[int]
    duplicate_pages: List[int]
    page_ids: List[int]
    partial: bool
    complete: bool


class ParseResult(TypedDict, total=False):
    ok: bool
    text: str
    result: Any
    coverage: Coverage
    assets: Dict[str, str]
    error: Optional[ErrorInfo]
    cache_raw_omitted: bool


class ChunkRecord(TypedDict, total=False):
    chunk_index: int
    source_page_start: Optional[int]
    source_page_end: Optional[int]
    coverage: Coverage
    provider_response: Any


class MergedResult(TypedDict, total=False):
    schema_version: int
    type: str
    chunks: List[ChunkRecord]
    merged: Dict[str, Any]
