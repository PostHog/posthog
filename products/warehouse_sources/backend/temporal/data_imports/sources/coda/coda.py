import time
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.coda.settings import CODA_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

CODA_BASE_URL = "https://coda.io/apis/v1"
PAGE_SIZE = 100
ROWS_PAGE_SIZE = 200
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5
# Coda's rate limits are per endpoint family: doc listing allows only
# 4 req/6s, while reads allow 100 req/6s — space requests accordingly.
DOC_LIST_INTERVAL_SECONDS = 1.6
READ_INTERVAL_SECONDS = 0.07


class CodaRetryableError(Exception):
    pass


def _get_session(api_token: str) -> requests.Session:
    return make_tracked_session(headers={"Authorization": f"Bearer {api_token}"}, redact_values=(api_token,))


def validate_credentials(api_token: str) -> bool:
    """Confirm the API token is valid with the whoami endpoint."""
    try:
        response = _get_session(api_token).get(
            f"{CODA_BASE_URL}/whoami",
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    session = _get_session(api_token)

    @retry(
        retry=retry_if_exception_type((CodaRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=5, max=120),
        reraise=True,
    )
    def fetch(path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{CODA_BASE_URL}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise CodaRetryableError(f"Coda API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Coda API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    def iterate_pages(
        path: str, page_size: int, interval: float, extra: dict[str, Any] | None = None
    ) -> Iterator[list[dict[str, Any]]]:
        token: Optional[str] = None
        while True:
            params: dict[str, Any] = {"limit": page_size, **(extra or {})}
            if token:
                # pageToken supersedes other params on continuation requests.
                params = {"pageToken": token}
            # Proactive pacing sits outside fetch's @retry boundary so tenacity
            # backoff isn't compounded by this sleep on every retry attempt.
            time.sleep(interval)
            data = fetch(path, params)
            items = data.get("items", []) or []
            if items:
                yield items
            token = data.get("nextPageToken")
            # Continue while Coda hands back a continuation token, even if this
            # page was empty — intermediate empty pages still precede more data.
            if not token:
                return

    def doc_ids() -> list[str]:
        # Direct access on the primary key so malformed API data fails fast
        # rather than silently dropping docs from the sync.
        return [doc["id"] for page in iterate_pages("/docs", PAGE_SIZE, DOC_LIST_INTERVAL_SECONDS) for doc in page]

    if endpoint == "docs":
        yield from iterate_pages("/docs", PAGE_SIZE, DOC_LIST_INTERVAL_SECONDS)
        return

    if endpoint == "tables":
        for doc_id in doc_ids():
            for page in iterate_pages(f"/docs/{quote(doc_id)}/tables", PAGE_SIZE, READ_INTERVAL_SECONDS):
                yield [{**table, "_doc_id": doc_id} for table in page]
        return

    if endpoint != "rows":
        raise ValueError(f"Unknown Coda endpoint: {endpoint!r}")

    # rows: fan out docs → tables → rows.
    for doc_id in doc_ids():
        tables: list[str] = []
        for page in iterate_pages(f"/docs/{quote(doc_id)}/tables", PAGE_SIZE, READ_INTERVAL_SECONDS):
            # Direct access on the primary key so malformed API data fails fast.
            tables.extend(table["id"] for table in page)

        for table_id in tables:
            for page in iterate_pages(
                f"/docs/{quote(doc_id)}/tables/{quote(table_id)}/rows",
                ROWS_PAGE_SIZE,
                READ_INTERVAL_SECONDS,
                # Column names instead of opaque column ids in `values`.
                extra={"useColumnNames": "true"},
            ):
                yield [{**row, "_doc_id": doc_id, "_table_id": table_id} for row in page]


def coda_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = CODA_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )
