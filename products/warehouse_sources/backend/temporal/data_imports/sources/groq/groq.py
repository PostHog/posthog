from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.groq.settings import (
    GROQ_ENDPOINTS,
    GroqEndpointConfig,
)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Bounds cursor pagination on `batches` so a malformed `next_cursor` (or an API that echoes the same
# cursor) can't loop forever. A structured warning is logged if the cap is ever reached. Per-org
# batch-job history is tiny, so this ceiling is far above any realistic page count.
MAX_PAGES = 1000


class GroqRetryableError(Exception):
    pass


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


@retry(
    retry=retry_if_exception_type(
        (
            GroqRetryableError,
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
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = session.get(url, headers=headers, params=params, timeout=60)

    # Groq applies org-level rate limits and returns 429 with a Retry-After header; tenacity's
    # backoff covers the wait. 5xx are transient too.
    if response.status_code == 429 or response.status_code >= 500:
        raise GroqRetryableError(f"Groq API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Groq API error: status={response.status_code}, body={response.text}, url={url}")
        # The API key rides in the Authorization header, not the URL, so raise_for_status()'s message
        # (which includes the URL) is safe to surface.
        response.raise_for_status()

    body = response.json()
    if not isinstance(body, dict):
        raise GroqRetryableError(f"Groq API returned an unexpected non-object response for url={url}")
    return body


def _next_cursor(body: dict[str, Any]) -> str | None:
    """Extract the next-page cursor from a Groq list response.

    Groq's batches endpoint documents cursor pagination via a `paging` object carrying `next_cursor`,
    passed back as the `cursor` query param. This could not be verified against the live API (no
    credentials were available), so absence of a `paging` object is treated as "single page" — the
    common case for the tiny per-org datasets these endpoints return.
    """
    paging = body.get("paging")
    if isinstance(paging, dict):
        cursor = paging.get("next_cursor")
        if cursor:
            return str(cursor)
    return None


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = GROQ_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across pages so urllib3 keeps the connection alive. The API key rides in the
    # Authorization header, so it's redacted from logged URLs and captured samples, and redirects are
    # disabled so the bearer token is never replayed to another host.
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
    url = f"{GROQ_BASE_URL}{config.path}"

    cursor: str | None = None
    for page in range(MAX_PAGES):
        params = {"cursor": cursor} if cursor else None
        body = _fetch_page(session, url, headers, logger, params=params)

        # All three list endpoints wrap results as {"object": "list", "data": [...]}.
        items = body.get("data", [])
        if not isinstance(items, list):
            raise GroqRetryableError(f"Groq API returned an unexpected non-list data field for url={url}")
        if items:
            yield items

        if not config.paginated:
            return

        cursor = _next_cursor(body)
        if not cursor:
            return

        if page == MAX_PAGES - 1:
            logger.warning(
                f"Groq: hit MAX_PAGES={MAX_PAGES} paginating {endpoint}; stopping. Some rows may be missing."
            )


def groq_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config: GroqEndpointConfig = GROQ_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(api_key=api_key, endpoint=endpoint, logger=logger),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
    )


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Confirm the API key is usable by listing models (cheap, always available with a valid key).

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` when the request never completed.
    """
    if not api_key.strip():
        return False, None

    try:
        session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
        response = session.get(f"{GROQ_BASE_URL}/models", headers=_get_headers(api_key), timeout=10)
    except Exception:
        return False, None

    return response.status_code == 200, response.status_code
