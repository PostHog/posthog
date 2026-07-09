from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.together_ai.settings import TOGETHER_AI_ENDPOINTS

TOGETHER_AI_BASE_URL = "https://api.together.xyz/v1"


class TogetherAIRetryableError(Exception):
    pass


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


@retry(
    retry=retry_if_exception_type(
        (
            TogetherAIRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(
    session: requests.Session,
    url: str,
    params: dict[str, str] | None,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> Any:
    response = session.get(url, params=params, headers=headers, timeout=60)

    # 429 (rate limit) and 5xx are transient — retry with backoff.
    if response.status_code == 429 or response.status_code >= 500:
        raise TogetherAIRetryableError(f"Together AI API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Never log response.text or the raw URL: the error body can echo account content and the
        # query string could carry request metadata. Log only status plus scheme/host/path.
        safe = urlsplit(response.url)
        safe_url = f"{safe.scheme}://{safe.netloc}{safe.path}"
        logger.error("Together AI API error", status=response.status_code, url=safe_url)
        # raise_for_status() would embed the full request URL in the exception, which is surfaced as
        # the schema's latest_error. Rebuild the error from scheme/host/path only so no request params
        # or response body reach stored error state. The "<status> Client Error: <reason> for url:
        # https://api.together.xyz" prefix stays stable for get_non_retryable_errors() matching.
        raise requests.HTTPError(
            f"{response.status_code} Client Error: {response.reason} for url: {safe_url}",
            response=response,
        )

    return response.json()


def _extract_rows(payload: Any, endpoint: str) -> list[dict[str, Any]]:
    """Unwrap a list response body.

    Together's list endpoints are inconsistent: fine-tunes/files/endpoints wrap rows in
    {"data": [...]}, batches/evaluations/models return a bare array. Accept both so an
    envelope change on their side doesn't break the sync.
    """
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("data"), list):
        rows = payload["data"]
    else:
        raise ValueError(f"Unexpected Together AI response shape for endpoint '{endpoint}': {type(payload).__name__}")

    return [row for row in rows if isinstance(row, dict)]


def get_rows(api_key: str, endpoint: str, logger: FilteringBoundLogger) -> Iterator[list[dict[str, Any]]]:
    endpoint_config = TOGETHER_AI_ENDPOINTS[endpoint]
    session = make_tracked_session(redact_values=(api_key,))

    url = f"{TOGETHER_AI_BASE_URL}{endpoint_config.path}"
    payload = _fetch(session, url, endpoint_config.params or None, _get_headers(api_key), logger)

    rows = _extract_rows(payload, endpoint)
    logger.debug("Together AI: fetched rows", count=len(rows), endpoint=endpoint)
    if rows:
        yield rows


def together_ai_source(api_key: str, endpoint: str, logger: FilteringBoundLogger) -> SourceResponse:
    endpoint_config = TOGETHER_AI_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(api_key=api_key, endpoint=endpoint, logger=logger),
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[endpoint_config.partition_key],
    )


def get_status_code(api_key: str, endpoint: str | None = None) -> int:
    """Cheap probe used by credential validation. Returns the HTTP status code."""
    if endpoint is not None and endpoint in TOGETHER_AI_ENDPOINTS:
        endpoint_config = TOGETHER_AI_ENDPOINTS[endpoint]
        path = endpoint_config.path
        params: dict[str, str] | None = endpoint_config.params or None
    else:
        # Files is account-scoped and small — a cheap token check.
        path = "/files"
        params = None

    url = f"{TOGETHER_AI_BASE_URL}{path}"
    response = make_tracked_session(redact_values=(api_key,)).get(
        url, params=params, headers=_get_headers(api_key), timeout=10
    )
    return response.status_code
