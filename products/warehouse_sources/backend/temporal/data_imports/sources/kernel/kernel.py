from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.kernel.settings import (
    KERNEL_ENDPOINTS,
    SENSITIVE_FIELDS,
    KernelEndpointConfig,
)

KERNEL_BASE_URL = "https://api.onkernel.com"

# Kernel caps list page size at 100 (1-100, default 20).
PAGE_SIZE = 100


class KernelRetryableError(Exception):
    pass


class KernelUnexpectedResponseError(Exception):
    """Raised when a list response is neither a JSON array nor a recognized wrapped shape.

    Every endpoint is a full refresh, so a body we can't parse must fail loudly: treating it
    as an empty page would let the sync "succeed" with zero rows and overwrite the existing
    warehouse table with nothing.
    """

    pass


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _build_url(path: str, params: dict[str, Any]) -> str:
    query = urlencode(params)
    return f"{KERNEL_BASE_URL}{path}?{query}" if query else f"{KERNEL_BASE_URL}{path}"


def _extract_items(body: Any) -> list[dict[str, Any]]:
    """Pull the row list out of a Kernel list response.

    Kernel signals pagination through headers (X-Has-More / X-Next-Offset), so the body is
    expected to be a bare JSON array. We defensively also accept the common wrapped shapes
    ({"data": [...]} etc.) since this has not been verified against a live API. An empty array
    (or empty wrapped list) is a legitimate "no more rows" signal. Any other shape is
    unexpected, and we raise rather than return [] - a silent empty result would let a full
    refresh overwrite the table with zero rows.
    """
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("data", "items", "results", "records"):
            value = body.get(key)
            if isinstance(value, list):
                return value
    raise KernelUnexpectedResponseError(f"Unexpected Kernel list response shape: {type(body).__name__}")


def _redact_sensitive_fields(item: Any) -> Any:
    """Drop credential-bearing fields (see SENSITIVE_FIELDS) before a row is batched.

    Kernel objects are written to the warehouse verbatim, so env vars and token-bearing
    live-view / CDP URLs would otherwise be queryable by any project user. `item` is untyped
    JSON, so non-dict rows pass through untouched.
    """
    if not isinstance(item, dict):
        return item
    return {key: value for key, value in item.items() if key.lower() not in SENSITIVE_FIELDS}


def _next_page(headers: Any, current_offset: int, page_len: int) -> tuple[bool, int]:
    """Return (has_more, next_offset) from the response headers, falling back to offset math."""
    has_more_header = str(headers.get("X-Has-More", "")).strip().lower()
    if has_more_header in ("true", "false"):
        has_more = has_more_header == "true"
    else:
        # No header: assume more pages only while a full page came back.
        has_more = page_len >= PAGE_SIZE

    next_offset_header = headers.get("X-Next-Offset")
    if next_offset_header is not None:
        try:
            return has_more, int(next_offset_header)
        except (TypeError, ValueError):
            pass
    return has_more, current_offset + page_len


@retry(
    retry=retry_if_exception_type(
        (
            KernelRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> requests.Response:
    response = session.get(url, headers=headers, timeout=60)

    # Kernel returns 429 with a Retry-After per-organization rate limit; honor it via retry backoff.
    if response.status_code == 429 or response.status_code >= 500:
        raise KernelRetryableError(f"Kernel API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Kernel API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Probe a cheap list endpoint. Returns (ok, status_code); status is None on transport failure."""
    url = _build_url("/apps", {"limit": 1})
    try:
        # capture=False: Kernel responses carry secret-bearing fields (see SENSITIVE_FIELDS)
        # that the generic HTTP-sample scrubber does not know to redact.
        response = make_tracked_session(capture=False).get(url, headers=_get_headers(api_key), timeout=10)
    except Exception:
        return False, None
    return response.status_code == 200, response.status_code


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[Any]:
    config = KERNEL_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # One session reused across every page so urllib3 keeps the connection alive.
    # capture=False: Kernel responses carry secret-bearing fields (see SENSITIVE_FIELDS) that the
    # generic HTTP-sample scrubber does not know to redact, and sampling happens before redaction.
    session = make_tracked_session(capture=False)

    # Full refresh only: no resumable offset state. A crashed sync restarts from offset 0 and
    # the pipeline overwrites the table on the first chunk, so re-fetched pages never duplicate
    # rows (full-refresh appends have no primary-key dedupe, so resuming mid-table would).
    offset = 0
    while True:
        params: dict[str, Any] = {"limit": PAGE_SIZE, "offset": offset, **config.extra_params}
        url = _build_url(config.path, params)
        response = _fetch_page(session, url, headers, logger)
        items = _extract_items(response.json())

        has_more, next_offset = _next_page(response.headers, offset, len(items))

        if not items:
            # An empty page doesn't necessarily mean the end - the API may signal more pages
            # via X-Has-More. Keep going, but stop if the offset can't advance (an empty page
            # with no X-Next-Offset would otherwise loop forever on the same request).
            if not has_more or next_offset <= offset:
                break
            offset = next_offset
            continue

        for item in items:
            batcher.batch(_redact_sensitive_fields(item))

        if batcher.should_yield():
            yield batcher.get_table()

        if not has_more:
            break

        offset = next_offset

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def kernel_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    endpoint_config: KernelEndpointConfig = KERNEL_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Full refresh for every endpoint (see settings.py) - no incremental watermark to order,
        # so the default ascending sort_mode is fine. Partitioning is left to the pipeline's
        # auto-detection (falls back to created_at when present); revisit once the live schema is
        # confirmed and a stable partition key per endpoint can be verified.
        sort_mode="asc",
    )
