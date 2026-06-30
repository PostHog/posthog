import dataclasses
from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.boldsign.settings import (
    BOLDSIGN_ENDPOINTS,
    BoldSignEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# BoldSign serves separate US and EU regional hosts; the account decides which one is live.
BOLDSIGN_HOSTS = {
    "us": "https://api.boldsign.com",
    "eu": "https://api-eu.boldsign.com",
}
PAGE_SIZE = 100
# Page-number access is capped at 10,000 records; document/list pages past it via NextCursor.
RECORD_CURSOR_THRESHOLD = 10_000
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5
# Backstop against a non-advancing cursor looping forever (10k records / 100 per page ≈ 100 pages,
# so this only trips on a genuinely misbehaving response).
MAX_PAGES = 100_000


class BoldSignRetryableError(Exception):
    pass


@dataclasses.dataclass
class BoldSignResumeConfig:
    # Page-number position for standard pagination.
    page: int = 1
    # Set once we cross the 10,000-record page cap on document/list and switch to cursor paging.
    # BoldSign describes this as an opaque value; the concrete type (int vs str) is unverified.
    next_cursor: str | int | None = None
    # Running total used to know when to switch to cursor paging.
    records_fetched: int = 0


def _base_url(region: str) -> str:
    host = BOLDSIGN_HOSTS.get(region)
    if host is None:
        raise ValueError(f"Invalid BoldSign region: {region}")
    return host


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "X-API-KEY": api_key,
        "Accept": "application/json",
    }


@retry(
    retry=retry_if_exception_type((BoldSignRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=2, max=90),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    # 429 (account-level rate limit, 2000/hour prod) and transient 5xx are retried with backoff.
    if response.status_code == 429 or response.status_code >= 500:
        raise BoldSignRetryableError(f"BoldSign API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"BoldSign API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(region: str, api_key: str) -> tuple[bool, str | None]:
    """Confirm the API key is genuine with one cheap, low-privilege list call."""
    url = f"{_base_url(region)}/v1/document/list"
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            url,
            headers=_get_headers(api_key),
            params={"Page": 1, "PageSize": 1},
            timeout=10,
        )
    except Exception as e:
        # A network error (timeout, connection failure) is not an auth problem — surface the
        # real cause instead of misreporting it as an invalid key and sending the user on a
        # fruitless key-rotation hunt during a transient outage.
        return False, f"Could not reach BoldSign: {e}"

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid BoldSign API key"
    return False, f"Unexpected response from BoldSign (status {response.status_code})"


def get_rows(
    region: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BoldSignResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = BOLDSIGN_ENDPOINTS[endpoint]
    url = f"{_base_url(region)}{config.path}"
    headers = _get_headers(api_key)
    session = make_tracked_session(redact_values=(api_key,))

    if not config.paginated:
        data = _fetch_page(session, url, headers, dict(config.extra_params), logger)
        items = data.get(config.data_key) or []
        if items:
            yield items
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume is not None else 1
    next_cursor = resume.next_cursor if resume is not None else None
    records_fetched = resume.records_fetched if resume is not None else 0
    if resume is not None:
        logger.debug(f"BoldSign: resuming {endpoint} from page={page}, next_cursor={next_cursor}")

    for _ in range(MAX_PAGES):
        params: dict[str, Any] = dict(config.extra_params)
        params["Page"] = page
        params["PageSize"] = PAGE_SIZE
        if next_cursor is not None:
            params["NextCursor"] = next_cursor

        data = _fetch_page(session, url, headers, params, logger)
        items = data.get(config.data_key) or []
        if not items:
            break

        yield items
        records_fetched += len(items)

        # A short page means we've reached the end.
        if len(items) < PAGE_SIZE:
            break

        if records_fetched >= RECORD_CURSOR_THRESHOLD:
            if not config.supports_cursor:
                # Page-number access is capped at 10k and this endpoint can't cursor past it.
                logger.warning(
                    f"BoldSign: {endpoint} reached the 10,000-record page-number cap; "
                    "remaining records are not synced (endpoint has no cursor pagination)."
                )
                break
            last_cursor = items[-1].get("cursor")
            # No (or non-advancing) cursor means we can't make progress; stop rather than loop.
            if last_cursor is None or last_cursor == next_cursor:
                break
            next_cursor = last_cursor
            page = 1
        else:
            page += 1

        # Save AFTER yielding the page so a crash re-fetches from the next position and never
        # skips a page; if we crash between the yield and this save, the prior state still points
        # at the just-yielded page, which merge dedupes on the primary key.
        resumable_source_manager.save_state(
            BoldSignResumeConfig(page=page, next_cursor=next_cursor, records_fetched=records_fetched)
        )


def boldsign_source(
    region: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BoldSignResumeConfig],
) -> SourceResponse:
    config: BoldSignEndpointConfig = BOLDSIGN_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            region=region,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        # Full refresh only — BoldSign timestamps are int64 epoch values, not datetimes, so there
        # is no stable datetime column to partition on.
        partition_mode=None,
    )
