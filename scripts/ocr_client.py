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

"""PaddleOCR HTTP client and document parsing orchestration."""

from email.utils import parsedate_to_datetime
import hashlib
import json
import logging
import math
import random
import threading
import time
from typing import Optional

import httpx

from config import (
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_MAX_REQUEST_MB,
    DEFAULT_MAX_RESPONSE_MB,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BACKOFF,
    DEFAULT_TASK_TIMEOUT,
    DEFAULT_TIMEOUT,
    FILE_TYPE_IMAGE,
    FILE_TYPE_PDF,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    MAX_RETRY_AFTER_SECONDS,
    MAX_TASK_TIMEOUT,
    _get_float_env,
    _get_int_env,
    get_doc_parsing_model,
    metric_add,
    resolve_access_token,
    resolve_api_url,
)
from contracts import ParseResult
from input_files import _detect_file_type, _load_file_as_base64
from response_parser import (
    _extract_markdown_assets,
    _extract_text,
    _validate_page_coverage,
    error_result,
)

logger = logging.getLogger(__name__)


def _redact_secret(value: str, secret: str) -> str:
    """Keep provider error messages useful without echoing an access token."""
    if not secret:
        return value
    return value.replace(secret, "[REDACTED]")


def _bounded_post(
    client: httpx.Client,
    api_url: str,
    params: dict,
    headers: dict,
    timeout: httpx.Timeout,
    max_response_bytes: int,
) -> httpx.Response:
    """Read an HTTP response incrementally and enforce its size limit."""
    with client.stream(
        "POST",
        api_url,
        json=params,
        headers=headers,
        timeout=timeout,
        follow_redirects=False,
    ) as streamed:
        content_length = streamed.headers.get("Content-Length")
        if content_length:
            try:
                if int(content_length) > max_response_bytes:
                    raise RuntimeError(
                        f"API response exceeds {max_response_bytes // 1024 // 1024} MB limit"
                    )
            except ValueError:
                pass

        chunks = []
        total_bytes = 0
        for chunk in streamed.iter_bytes():
            total_bytes += len(chunk)
            if total_bytes > max_response_bytes:
                raise RuntimeError(
                    f"API response exceeds {max_response_bytes // 1024 // 1024} MB limit"
                )
            chunks.append(chunk)
        request = getattr(streamed, "request", None)
        if not isinstance(request, httpx.Request):
            request = None
        return httpx.Response(
            streamed.status_code,
            headers=streamed.headers,
            content=b"".join(chunks),
            request=request,
        )


def _make_api_request(
    api_url: str,
    token: str,
    params: dict,
    client: Optional[httpx.Client] = None,
    metrics: Optional[dict[str, float]] = None,
    deadline: Optional[float] = None,
    cancel_event: Optional[threading.Event] = None,
) -> dict:
    """Make a bounded, retryable PaddleOCR document parsing request."""
    headers = {
        "Authorization": f"token {token}",
        "Content-Type": "application/json",
        "Client-Platform": "official-skill",
    }
    stable_params = json_dumps_stable(params)
    headers["Idempotency-Key"] = hashlib.sha256(
        stable_params.encode("utf-8")
    ).hexdigest()

    timeout_seconds = _get_float_env(
        "PADDLEOCR_DOC_PARSING_TIMEOUT",
        DEFAULT_TIMEOUT,
        min_value=1,
        max_value=MAX_TASK_TIMEOUT,
    )
    connect_timeout_seconds = _get_float_env(
        "PADDLEOCR_DOC_PARSING_CONNECT_TIMEOUT",
        DEFAULT_CONNECT_TIMEOUT,
        min_value=1,
        max_value=300,
    )
    max_retries = _get_int_env(
        "PADDLEOCR_DOC_PARSING_MAX_RETRIES",
        DEFAULT_MAX_RETRIES,
        min_value=0,
        max_value=5,
    )
    retry_backoff_seconds = _get_float_env(
        "PADDLEOCR_DOC_PARSING_RETRY_BACKOFF",
        DEFAULT_RETRY_BACKOFF,
        min_value=0.1,
        max_value=60,
    )
    max_response_bytes = int(
        _get_float_env(
            "PADDLEOCR_DOC_PARSING_MAX_RESPONSE_MB",
            DEFAULT_MAX_RESPONSE_MB,
            min_value=1,
            max_value=MAX_RESPONSE_BYTES / 1024 / 1024,
        )
        * 1024
        * 1024
    )
    max_request_bytes = int(
        _get_float_env(
            "PADDLEOCR_DOC_PARSING_MAX_REQUEST_MB",
            DEFAULT_MAX_REQUEST_MB,
            min_value=1,
            max_value=MAX_REQUEST_BYTES / 1024 / 1024,
        )
        * 1024
        * 1024
    )
    if len(stable_params.encode("utf-8")) > max_request_bytes:
        raise RuntimeError(
            f"API request exceeds {max_request_bytes // 1024 // 1024} MB limit"
        )

    timeout = httpx.Timeout(timeout_seconds, connect=connect_timeout_seconds)
    owned_client = client is None
    if owned_client:
        client = httpx.Client(timeout=timeout, follow_redirects=False)

    response = None
    request_started_at = time.perf_counter()
    try:
        for attempt in range(max_retries + 1):
            metric_add(metrics, "api_attempt_count", 1.0)
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("OCR request cancelled after another chunk failed")
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise RuntimeError("OCR task deadline exceeded")
            request_timeout_seconds = (
                timeout_seconds
                if remaining is None
                else min(timeout_seconds, remaining)
            )
            request_timeout = httpx.Timeout(
                request_timeout_seconds,
                connect=min(connect_timeout_seconds, request_timeout_seconds),
            )
            try:
                response = _bounded_post(
                    client,
                    api_url,
                    params,
                    headers,
                    request_timeout,
                    max_response_bytes,
                )
            except httpx.TimeoutException:
                error_message = f"API request timed out after {timeout_seconds}s"
                should_retry = True
            except httpx.RequestError as exc:
                error_message = f"API request failed: {exc}"
                should_retry = True
            else:
                response_headers = getattr(response, "headers", {}) or {}
                content_length = response_headers.get("Content-Length")
                if content_length:
                    try:
                        if int(content_length) > max_response_bytes:
                            raise RuntimeError(
                                f"API response exceeds "
                                f"{max_response_bytes // 1024 // 1024} MB limit"
                            )
                    except ValueError:
                        pass
                if response.status_code == 200:
                    if deadline is not None and time.monotonic() > deadline:
                        raise RuntimeError("OCR task deadline exceeded")
                    break

                error_code = None
                try:
                    error_body = response.json()
                    if isinstance(error_body, dict):
                        error_code = error_body.get("errorCode")
                except Exception:
                    pass
                provider_code = (
                    f", provider code {error_code}"
                    if error_code is not None
                    else ""
                )
                if response.status_code == 403:
                    raise RuntimeError("Authentication failed (403)")
                error_message = (
                    f"API rate limit exceeded (429){provider_code}"
                    if response.status_code == 429
                    else (
                        f"API service error ({response.status_code}){provider_code}"
                        if response.status_code >= 500
                        else f"API error ({response.status_code}){provider_code}"
                    )
                )
                should_retry = response.status_code == 429 or response.status_code >= 500

            if attempt >= max_retries or not should_retry:
                raise RuntimeError(error_message)

            sleep_seconds = _retry_sleep_seconds(
                response,
                retry_backoff_seconds,
                attempt,
            )
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("OCR task deadline exceeded")
                sleep_seconds = min(sleep_seconds, remaining)
            logger.warning(
                "PaddleOCR HTTP attempt %s/%s failed: %s. Retrying in %.1fs",
                attempt + 1,
                max_retries + 1,
                _redact_secret(error_message, token),
                sleep_seconds,
            )
            if cancel_event is not None:
                if cancel_event.wait(sleep_seconds):
                    raise RuntimeError("OCR request cancelled after another chunk failed")
            else:
                time.sleep(sleep_seconds)
    finally:
        metric_add(
            metrics,
            "api_request_seconds",
            time.perf_counter() - request_started_at,
        )
        if owned_client:
            client.close()

    if response is None:
        raise RuntimeError("API request did not return a response")
    response_content = getattr(response, "content", b"")
    if (
        isinstance(response_content, (bytes, bytearray))
        and len(response_content) > max_response_bytes
    ):
        raise RuntimeError(
            f"API response exceeds {max_response_bytes // 1024 // 1024} MB limit"
        )

    try:
        result = response.json()
    except Exception as exc:
        raise RuntimeError(
            f"Invalid JSON response: {_redact_secret(response.text[:200], token)}"
        ) from exc
    if not isinstance(result, dict):
        raise RuntimeError(
            "Invalid JSON response: top-level response must be an object"
        )
    if result.get("errorCode", 0) != 0:
        raise RuntimeError(f"API error (provider code {result.get('errorCode')})")
    return result


def json_dumps_stable(payload: object) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _retry_sleep_seconds(
    response: Optional[httpx.Response],
    backoff_seconds: float,
    attempt: int,
) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                retry_seconds = float(retry_after)
                if math.isfinite(retry_seconds):
                    return min(MAX_RETRY_AFTER_SECONDS, max(0.1, retry_seconds))
            except ValueError:
                pass
            try:
                retry_at = parsedate_to_datetime(retry_after).timestamp()
                return min(
                    MAX_RETRY_AFTER_SECONDS,
                    max(0.1, retry_at - time.time()),
                )
            except (TypeError, ValueError, OverflowError):
                pass
    jitter = random.uniform(0, min(0.5, backoff_seconds))
    return backoff_seconds * (2**attempt) + jitter


def parse_document(
    file_path: Optional[str] = None,
    file_url: Optional[str] = None,
    file_type: Optional[int] = None,
    api_url: Optional[str] = None,
    token: Optional[str] = None,
    client: Optional[httpx.Client] = None,
    metrics: Optional[dict[str, float]] = None,
    expected_pages: Optional[int] = None,
    deadline: Optional[float] = None,
    cancel_event: Optional[threading.Event] = None,
    allow_insecure_http: bool = False,
    **options,
) -> ParseResult:
    """Prepare, submit, and validate one document parsing request."""
    if not file_path and not file_url:
        return error_result("INPUT_ERROR", "file_path or file_url required")
    if file_type is not None and file_type not in (FILE_TYPE_PDF, FILE_TYPE_IMAGE):
        return error_result("INPUT_ERROR", "file_type must be 0 (PDF) or 1 (Image)")

    if deadline is None:
        deadline = time.monotonic() + _get_float_env(
            "PADDLEOCR_DOC_PARSING_TASK_TIMEOUT",
            DEFAULT_TASK_TIMEOUT,
            min_value=10,
            max_value=MAX_TASK_TIMEOUT,
        )

    config_started_at = time.perf_counter()
    try:
        api_url, _ = resolve_api_url(
            api_url,
            allow_insecure_http=allow_insecure_http,
        )
        token, _ = resolve_access_token(token)
    except ValueError as exc:
        return error_result("CONFIG_ERROR", str(exc))
    finally:
        metric_add(
            metrics,
            "config_lookup_seconds",
            time.perf_counter() - config_started_at,
        )

    input_prepare_started_at = time.perf_counter()
    try:
        if file_url:
            params = {"file": file_url}
            resolved_file_type = file_type
        else:
            resolved_file_type = (
                file_type
                if file_type is not None
                else _detect_file_type(file_path)
            )
            params = {
                "file": _load_file_as_base64(file_path, resolved_file_type),
            }
        params.update(options)
        params.setdefault("model", get_doc_parsing_model())
        if resolved_file_type is not None:
            params["fileType"] = resolved_file_type
        elif file_url:
            params.pop("fileType", None)
    except (ValueError, FileNotFoundError, OSError) as exc:
        return error_result("INPUT_ERROR", str(exc))
    except Exception as exc:
        return error_result(
            "INPUT_ERROR",
            f"{type(exc).__name__}: {str(exc)[:500]}",
        )
    finally:
        metric_add(
            metrics,
            "input_prepare_seconds",
            time.perf_counter() - input_prepare_started_at,
        )

    try:
        result = _make_api_request(
            api_url,
            token,
            params,
            client=client,
            metrics=metrics,
            deadline=deadline,
            cancel_event=cancel_event,
        )
    except Exception as exc:
        return error_result(
            "API_ERROR",
            f"{type(exc).__name__}: {_redact_secret(str(exc)[:500], token)}",
        )

    extract_started_at = time.perf_counter()
    try:
        coverage = _validate_page_coverage(
            result,
            expected_pages=expected_pages,
        )
        text = _extract_text(result)
    except ValueError as exc:
        return error_result("API_ERROR", str(exc))
    finally:
        metric_add(
            metrics,
            "text_extract_seconds",
            time.perf_counter() - extract_started_at,
        )

    return {
        "ok": True,
        "text": text,
        "result": result,
        "coverage": coverage,
        "assets": _extract_markdown_assets(result),
        "error": None,
    }
