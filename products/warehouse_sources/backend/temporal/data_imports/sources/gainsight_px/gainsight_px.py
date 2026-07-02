import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_px.settings import (
    EPOCH_MILLIS_FIELDS,
    GAINSIGHT_PX_ENDPOINTS,
    GAINSIGHT_PX_HOSTS,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
# A defensive upper bound on pages fetched per endpoint. The loops terminate on the API's own
# last-page signals; this only guards against a mis-signalling API scrolling forever.
MAX_PAGES = 100_000


class GainsightPxRetryableError(Exception):
    pass


@dataclasses.dataclass
class GainsightPxResumeConfig:
    # Cursor token for scroll-paginated endpoints (users/accounts). None starts at the first page.
    scroll_id: str | None = None
    # Next page index for page-number-paginated endpoints (features/segments/…). None starts at 0.
    page_number: int | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {"X-APTRINSIC-API-KEY": api_key, "Accept": "application/json"}


def _base_url(region: str) -> str:
    return GAINSIGHT_PX_HOSTS.get(region) or GAINSIGHT_PX_HOSTS["us"]


def _build_url(base: str, params: dict[str, Any]) -> str:
    return f"{base}?{urlencode(params)}" if params else base


def _normalize_row(item: dict[str, Any]) -> dict[str, Any]:
    """Convert the API's epoch-millisecond date fields to real datetimes.

    The warehouse then types these columns as timestamps (useful for querying) and the partitioner
    reads the datetime directly rather than misinterpreting raw millis as epoch seconds. `bool` is
    excluded because it's an `int` subclass and no boolean field is a date.
    """
    for name in EPOCH_MILLIS_FIELDS:
        value = item.get(name)
        if isinstance(value, int) and not isinstance(value, bool):
            item[name] = datetime.fromtimestamp(value / 1000, tz=UTC)
    return item


@retry(
    retry=retry_if_exception_type(
        (
            GainsightPxRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    # 429 (rate limit) and 5xx are transient — retry. Everything else (401/403/400/404) is terminal;
    # `raise_for_status` surfaces it and `get_non_retryable_errors` maps auth failures to a message.
    if response.status_code == 429 or response.status_code >= 500:
        raise GainsightPxRetryableError(f"Gainsight PX API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Gainsight PX API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str, region: str) -> bool:
    url = _build_url(f"{_base_url(region)}/accounts", {"pageSize": 1})
    try:
        # `retry=Retry(total=0)` leaves retries to tenacity elsewhere; `redact_values` masks the API
        # key in captured samples since `X-APTRINSIC-API-KEY` isn't a name-redacted auth header.
        session = make_tracked_session(retry=Retry(total=0), redact_values=(api_key,))
        response = session.get(url, headers=_get_headers(api_key), timeout=REQUEST_TIMEOUT_SECONDS)
        return response.status_code == 200
    except (requests.ConnectionError, requests.Timeout):
        # Only transient network failures should read as "invalid credentials"; programming errors
        # (TypeError, AttributeError, …) must surface rather than being masked as a bad key.
        return False


def _iter_scroll_pages(
    session: requests.Session,
    base: str,
    endpoint: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GainsightPxResumeConfig],
    resume: GainsightPxResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    """Page a scroll-paginated endpoint (users/accounts), yielding one page of rows at a time.

    Gainsight PX warns not to rely on `scrollId` becoming null, so the loop stops when a page returns
    fewer records than requested. State is saved AFTER yielding each page so a crash re-yields the
    last page (merge dedupes on the primary key) rather than skipping it.
    """
    config = GAINSIGHT_PX_ENDPOINTS[endpoint]
    scroll_id = resume.scroll_id if resume else None

    for _ in range(MAX_PAGES):
        params: dict[str, Any] = {"pageSize": config.page_size}
        if scroll_id:
            params["scrollId"] = scroll_id

        data = _fetch_page(session, _build_url(f"{base}{config.path}", params), headers, logger)
        records = data.get(config.data_key) or []
        if records:
            yield [_normalize_row(record) for record in records]

        next_scroll_id = data.get("scrollId")
        if len(records) < config.page_size or not next_scroll_id:
            return

        scroll_id = next_scroll_id
        resumable_source_manager.save_state(GainsightPxResumeConfig(scroll_id=scroll_id))
    else:
        logger.warning(f"Gainsight PX: hit MAX_PAGES page cap for endpoint={endpoint}")


def _iter_numbered_pages(
    session: requests.Session,
    base: str,
    endpoint: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GainsightPxResumeConfig],
    resume: GainsightPxResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    """Page a page-number-paginated endpoint (features/segments/engagements/articles/kcbot).

    These responses carry an `isLastPage` flag; we also stop on a short page as a belt-and-braces
    guard. State (the next page index) is saved after each yielded page for the same reason as scroll.
    """
    config = GAINSIGHT_PX_ENDPOINTS[endpoint]
    page_number = resume.page_number if resume and resume.page_number is not None else 0

    for _ in range(MAX_PAGES):
        params = {"pageSize": config.page_size, "pageNumber": page_number}
        data = _fetch_page(session, _build_url(f"{base}{config.path}", params), headers, logger)
        records = data.get(config.data_key) or []
        if records:
            yield [_normalize_row(record) for record in records]

        if data.get("isLastPage") or len(records) < config.page_size:
            return

        page_number += 1
        resumable_source_manager.save_state(GainsightPxResumeConfig(page_number=page_number))
    else:
        logger.warning(f"Gainsight PX: hit MAX_PAGES page cap for endpoint={endpoint}")


def get_rows(
    api_key: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GainsightPxResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = GAINSIGHT_PX_ENDPOINTS[endpoint]
    base = _base_url(region)
    headers = _get_headers(api_key)
    # One session reused across every page so urllib3 keeps the connection alive.
    # `retry=Retry(total=0)` leaves retries to tenacity in `_fetch_page` (rather than stacking urllib3
    # retries under them); `redact_values` masks the API key in captured samples since the custom
    # `X-APTRINSIC-API-KEY` header isn't one of the name-redacted auth headers.
    session = make_tracked_session(retry=Retry(total=0), redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.pagination == "scroll":
        yield from _iter_scroll_pages(session, base, endpoint, headers, logger, resumable_source_manager, resume)
    else:
        yield from _iter_numbered_pages(session, base, endpoint, headers, logger, resumable_source_manager, resume)


def gainsight_px_source(
    api_key: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GainsightPxResumeConfig],
) -> SourceResponse:
    config = GAINSIGHT_PX_ENDPOINTS[endpoint]
    partition_key = config.partition_key

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            region=region,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
    )
