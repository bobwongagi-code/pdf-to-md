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

"""Configuration, credentials, and runtime limits for the OCR client."""

import hashlib
import logging
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 600
DEFAULT_CONNECT_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_BACKOFF = 1.5
DEFAULT_LARGE_FILE_WARNING_MB = 50
DEFAULT_MAX_LOCAL_FILE_MB = 200
DEFAULT_MAX_RESPONSE_MB = 64
DEFAULT_MAX_REQUEST_MB = 384
DEFAULT_TASK_TIMEOUT = 1800
DEFAULT_MODEL = "PaddleOCR-VL-1.6"
API_GUIDE_URL = "https://paddleocr.com"
FILE_TYPE_PDF = 0
FILE_TYPE_IMAGE = 1
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp")
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "pdf-to-md" / "config.env"
DEFAULT_KEYCHAIN_SERVICE = "pdf-to-md.paddleocr"
DEFAULT_KEYCHAIN_ACCOUNT = "PADDLEOCR_ACCESS_TOKEN"
MAX_RETRY_AFTER_SECONDS = 60.0
MAX_TASK_TIMEOUT = 4 * 60 * 60
MAX_RESPONSE_BYTES = 256 * 1024 * 1024
MAX_REQUEST_BYTES = 512 * 1024 * 1024
MAX_LOCAL_FILE_BYTES = 2 * 1024 * 1024 * 1024
SUPPORTED_FILE_TYPES = {FILE_TYPE_PDF, FILE_TYPE_IMAGE}
DEFAULT_MAX_PAGES_PER_REQUEST = 20
DEFAULT_MAX_CHUNK_WORKERS = 1
MAX_CHUNK_WORKERS = 8
DEFAULT_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60
DEFAULT_CACHE_MAX_MB = 512
MAX_CACHE_MAX_MB = 8192
DEFAULT_MAX_ASSET_COUNT = 500
DEFAULT_MAX_ASSET_TOTAL_MB = 512
MAX_ASSET_TOTAL_MB = 4096
DEFAULT_ASSET_TOTAL_TIMEOUT = 300
MAX_ASSET_TOTAL_TIMEOUT = 3600

# Only these non-secret settings may be persisted in the Finder config file.
LOCAL_CONFIG_KEYS = frozenset(
    {
        "PADDLEOCR_DOC_PARSING_API_URL",
        "PADDLEOCR_DOC_PARSING_MODEL",
        "PADDLEOCR_DOC_PARSING_TIMEOUT",
        "PADDLEOCR_DOC_PARSING_CONNECT_TIMEOUT",
        "PADDLEOCR_DOC_PARSING_MAX_RETRIES",
        "PADDLEOCR_DOC_PARSING_RETRY_BACKOFF",
        "PADDLEOCR_DOC_PARSING_MAX_LOCAL_FILE_MB",
        "PADDLEOCR_DOC_PARSING_MAX_REQUEST_MB",
        "PADDLEOCR_DOC_PARSING_MAX_RESPONSE_MB",
        "PADDLEOCR_DOC_PARSING_TASK_TIMEOUT",
        "PADDLEOCR_DOC_PARSING_MAX_PAGES_PER_REQUEST",
        "PADDLEOCR_DOC_PARSING_MAX_CHUNK_WORKERS",
        "PADDLEOCR_DOC_PARSING_CACHE_TTL_SECONDS",
        "PADDLEOCR_DOC_PARSING_CACHE_MAX_MB",
        "PADDLEOCR_DOC_PARSING_ASSET_TIMEOUT",
        "PADDLEOCR_DOC_PARSING_MAX_ASSET_COUNT",
        "PADDLEOCR_DOC_PARSING_MAX_ASSET_TOTAL_MB",
        "PADDLEOCR_DOC_PARSING_ASSET_TOTAL_TIMEOUT",
        "PADDLEOCR_ALLOW_INSECURE_HTTP",
    }
)


def metric_add(metrics: Optional[dict[str, float]], key: str, delta: float) -> None:
    if metrics is None:
        return
    metrics[key] = metrics.get(key, 0.0) + delta


def _get_env(key: str, *fallback_keys: str) -> str:
    """Get an environment variable with optional fallback keys."""
    value = os.getenv(key, "").strip()
    if value:
        return value
    for fallback in fallback_keys:
        value = os.getenv(fallback, "").strip()
        if value:
            logger.debug("Using fallback env var: %s", fallback)
            return value
    return ""


def read_local_config_values(path: Optional[Path] = None) -> dict[str, str]:
    """Read supported non-secret settings from Finder configuration."""
    config_path = path or Path(
        _get_env("PDF_TO_MD_CONFIG_FILE") or DEFAULT_CONFIG_PATH
    ).expanduser()
    if not config_path.is_file():
        return {}
    values: dict[str, str] = {}
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.debug("Failed to read local config %s: %s", config_path, exc)
        return values
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        setting_key, value = line.split("=", 1)
        setting_key = setting_key.strip()
        if setting_key in LOCAL_CONFIG_KEYS:
            values[setting_key] = value.strip().strip('"').strip("'")
    return values


def _get_local_config(key: str) -> str:
    """Read one supported non-secret setting from Finder configuration."""
    if key not in LOCAL_CONFIG_KEYS:
        return ""
    return read_local_config_values().get(key, "")


def _get_setting(key: str) -> str:
    """Read a non-secret setting from the environment, then local config."""
    return _get_env(key) or _get_local_config(key)


def _keychain_enabled() -> bool:
    return _get_env("PADDLEOCR_DISABLE_KEYCHAIN").lower() not in {
        "1",
        "true",
        "yes",
    }


def _get_keychain_secret(service: str, account: str) -> str:
    """Read a secret from macOS Keychain using the built-in security CLI."""
    if sys.platform != "darwin" or not _keychain_enabled():
        return ""
    security_bin = shutil.which("security")
    if not security_bin:
        return ""
    try:
        result = subprocess.run(
            [
                security_bin,
                "find-generic-password",
                "-s",
                service,
                "-a",
                account,
                "-w",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("Keychain lookup failed: %s", exc)
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _get_access_token() -> tuple[str, str]:
    token = _get_env("PADDLEOCR_ACCESS_TOKEN")
    if token:
        return token, "environment"

    service = _get_env("PADDLEOCR_KEYCHAIN_SERVICE") or DEFAULT_KEYCHAIN_SERVICE
    account = _get_env("PADDLEOCR_KEYCHAIN_ACCOUNT") or DEFAULT_KEYCHAIN_ACCOUNT
    token = _get_keychain_secret(service, account)
    if token:
        return token, f"keychain:{service}/{account}"
    return "", ""


def _get_float_env(
    key: str,
    default: float,
    min_value: float,
    max_value: Optional[float] = None,
) -> float:
    """Read a finite float setting, falling back when it is invalid."""
    raw_value = _get_setting(key)
    if not raw_value:
        return default
    try:
        value = float(raw_value)
    except ValueError:
        logger.warning("Invalid %s=%r; using default %s", key, raw_value, default)
        return default
    if not math.isfinite(value):
        logger.warning("Invalid %s=%r; using default %s", key, raw_value, default)
        return default
    if value < min_value or (max_value is not None and value > max_value):
        logger.warning(
            "Invalid %s=%r; expected %s-%s. Using default %s",
            key,
            raw_value,
            min_value,
            max_value if max_value is not None else "infinity",
            default,
        )
        return default
    return value


def _get_int_env(
    key: str,
    default: int,
    min_value: int,
    max_value: Optional[int] = None,
) -> int:
    """Read an integer setting, falling back when it is invalid."""
    raw_value = _get_setting(key)
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        logger.warning("Invalid %s=%r; using default %s", key, raw_value, default)
        return default
    if value < min_value or (max_value is not None and value > max_value):
        logger.warning(
            "Invalid %s=%r; expected %s-%s. Using default %s",
            key,
            raw_value,
            min_value,
            max_value if max_value is not None else "infinity",
            default,
        )
        return default
    return value


def get_max_pages_per_request(override: Optional[int] = None) -> int:
    raw_value = (
        str(override)
        if override is not None
        else _get_setting("PADDLEOCR_DOC_PARSING_MAX_PAGES_PER_REQUEST")
    )
    if not raw_value:
        return DEFAULT_MAX_PAGES_PER_REQUEST
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError("chunk page count must be an integer") from exc
    if not 1 <= value <= 100:
        raise ValueError("chunk page count must be between 1 and 100")
    return value


def get_max_chunk_workers(override: Optional[int] = None) -> int:
    raw_value = (
        str(override)
        if override is not None
        else _get_setting("PADDLEOCR_DOC_PARSING_MAX_CHUNK_WORKERS")
    )
    if not raw_value:
        return DEFAULT_MAX_CHUNK_WORKERS
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError("chunk worker count must be an integer") from exc
    if not 1 <= value <= MAX_CHUNK_WORKERS:
        raise ValueError(
            f"chunk worker count must be between 1 and {MAX_CHUNK_WORKERS}"
        )
    return value


def get_cache_ttl_seconds() -> int:
    raw = _get_setting("PADDLEOCR_DOC_PARSING_CACHE_TTL_SECONDS") or str(
        DEFAULT_CACHE_TTL_SECONDS
    )
    try:
        value = int(raw)
        if not 1 <= value <= 90 * 24 * 60 * 60:
            raise ValueError
        return value
    except (ValueError, TypeError):
        return int(DEFAULT_CACHE_TTL_SECONDS)


def get_cache_max_bytes() -> int:
    value = _get_float_env(
        "PADDLEOCR_DOC_PARSING_CACHE_MAX_MB",
        DEFAULT_CACHE_MAX_MB,
        min_value=1,
        max_value=MAX_CACHE_MAX_MB,
    )
    return int(value * 1024 * 1024)


def get_task_timeout_seconds() -> float:
    return _get_float_env(
        "PADDLEOCR_DOC_PARSING_TASK_TIMEOUT",
        DEFAULT_TASK_TIMEOUT,
        min_value=10,
        max_value=MAX_TASK_TIMEOUT,
    )


def get_max_asset_count() -> int:
    return _get_int_env(
        "PADDLEOCR_DOC_PARSING_MAX_ASSET_COUNT",
        DEFAULT_MAX_ASSET_COUNT,
        min_value=1,
        max_value=5000,
    )


def get_max_asset_total_bytes() -> int:
    value = _get_float_env(
        "PADDLEOCR_DOC_PARSING_MAX_ASSET_TOTAL_MB",
        DEFAULT_MAX_ASSET_TOTAL_MB,
        min_value=1,
        max_value=MAX_ASSET_TOTAL_MB,
    )
    return int(value * 1024 * 1024)


def get_asset_total_timeout_seconds() -> float:
    return _get_float_env(
        "PADDLEOCR_DOC_PARSING_ASSET_TOTAL_TIMEOUT",
        DEFAULT_ASSET_TOTAL_TIMEOUT,
        min_value=1,
        max_value=MAX_ASSET_TOTAL_TIMEOUT,
    )


def resolve_api_url(
    api_url: Optional[str] = None,
    *,
    allow_insecure_http: bool = False,
) -> tuple[str, str]:
    """Resolve and validate the API URL without touching credentials."""
    source = "argument" if api_url else (
        "environment"
        if _get_env("PADDLEOCR_DOC_PARSING_API_URL")
        else "local-config"
    )
    api_url = api_url or _get_setting("PADDLEOCR_DOC_PARSING_API_URL")
    if not api_url:
        raise ValueError(
            "PADDLEOCR_DOC_PARSING_API_URL not configured. "
            f"Get your API at: {API_GUIDE_URL}"
        )

    api_url = api_url.strip()
    if "://" not in api_url:
        api_url = f"https://{api_url}"
    parsed = urlparse(api_url)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("PADDLEOCR_DOC_PARSING_API_URL must use http:// or https://")
    try:
        hostname = parsed.hostname
        parsed.port
    except ValueError as exc:
        raise ValueError(
            "PADDLEOCR_DOC_PARSING_API_URL contains an invalid port"
        ) from exc
    if not hostname or parsed.username or parsed.password:
        raise ValueError(
            "PADDLEOCR_DOC_PARSING_API_URL must contain a valid host without credentials"
        )
    if parsed.query or parsed.fragment:
        raise ValueError(
            "PADDLEOCR_DOC_PARSING_API_URL must not contain a query or fragment"
        )
    if scheme != "https":
        allow_insecure = (
            allow_insecure_http
            or _get_env("PADDLEOCR_ALLOW_INSECURE_HTTP").lower()
            in {"1", "true", "yes"}
            or _get_setting("PADDLEOCR_ALLOW_INSECURE_HTTP").lower()
            in {"1", "true", "yes"}
        )
        if not allow_insecure or hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError(
                "PADDLEOCR_DOC_PARSING_API_URL must use HTTPS. "
                "Set PADDLEOCR_ALLOW_INSECURE_HTTP=1 only for loopback development."
            )
    api_path = parsed.path.rstrip("/")
    if not api_path.lower().endswith("/layout-parsing"):
        raise ValueError(
            "PADDLEOCR_DOC_PARSING_API_URL must be a full endpoint ending with "
            "/layout-parsing. Example: "
            "https://your-service.paddleocr.com/layout-parsing"
        )
    return f"{scheme}://{parsed.netloc}{api_path}", source


def resolve_access_token(token: Optional[str] = None) -> tuple[str, str]:
    """Resolve an explicit, environment, or Keychain credential."""
    if token:
        return token, "argument"
    token, token_source = _get_access_token()
    if not token:
        raise ValueError(
            "PADDLEOCR_ACCESS_TOKEN not configured in environment or macOS Keychain. "
            f"Get your API at: {API_GUIDE_URL}"
        )
    return token, token_source


def get_config_with_sources() -> tuple[str, str, str, str]:
    api_url, api_url_source = resolve_api_url()
    token, token_source = resolve_access_token()
    return api_url, token, api_url_source, token_source


def get_config() -> tuple[str, str]:
    api_url, token, _, _ = get_config_with_sources()
    return api_url, token


def get_doc_parsing_model() -> str:
    return _get_setting("PADDLEOCR_DOC_PARSING_MODEL") or DEFAULT_MODEL


def get_endpoint_origin(api_url: str) -> str:
    parsed = urlparse(api_url)
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname or ''}{port}"


def get_credential_scope_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


# Kept for callers that used the old private helper through lib.py.
_metric_add = metric_add
