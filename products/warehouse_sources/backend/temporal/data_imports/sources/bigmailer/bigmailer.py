import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.bigmailer.settings import (
    BIGMAILER_ENDPOINTS,
    BigMailerEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

BIGMAILER_BASE_URL = "https://api.bigmailer.io/v1"
# The API caps list responses at 100 objects per page; request the max to minimise round trips
# against the 10 req/s account rate limit.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60

# Stable substring matched by BigMailerSource.get_non_retryable_errors to permanently fail the sync
# on a credential problem instead of retrying. Kept identical to the raised exception text.
AUTH_ERROR_MESSAGE = "BigMailer API key is invalid or lacks the required permissions"


class BigMailerAuthError(Exception):
    """Raised when the API rejects the key (HTTP 400 'Invalid api key', 401, or 403).

    An invalid or insufficiently-permissioned key can never be fixed by retrying, so this is
    surfaced as a non-retryable error rather than looping the sync.
    """


@dataclasses.dataclass
class BigMailerResumeConfig:
    # Cursor for the next page to fetch. None starts a list at its first page.
    cursor: str | None = None
    # The brand currently being processed. A stable brand-ID bookmark (not a positional index) so a
    # brand added or removed between a crash and the retry can't resume us into the wrong brand. None
    # for the account-level endpoints (brands, users).
    brand_id: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key, "Accept": "application/json"}


def _build_url(path: str, cursor: str | None) -> str:
    params: dict[str, Any] = {"limit": PAGE_SIZE}
    if cursor:
        params["cursor"] = cursor
    return f"{BIGMAILER_BASE_URL}{path}?{urlencode(params)}"


def _fetch_page(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict:
    """Fetch a single list page. The tracked session retries 429/5xx with backoff, so by the time we
    inspect the response any transient errors are already exhausted."""
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    # An invalid key returns 400 with `{"type": "invalid_request_error", "message": "Invalid api key"}`;
    # insufficient permissions surface as 401/403. None of these are retryable.
    if response.status_code in (401, 403) or (response.status_code == 400 and "api key" in response.text.lower()):
        raise BigMailerAuthError(AUTH_ERROR_MESSAGE)

    if not response.ok:
        logger.error(f"BigMailer API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _iter_pages(
    session: requests.Session,
    path: str,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[BigMailerResumeConfig],
    start_cursor: str | None,
    brand_id: str | None,
) -> Iterator[list[dict]]:
    """Page through a list endpoint, yielding one page of raw rows at a time.

    Saves resume state AFTER yielding each page (pointing at the next page) so a crash re-fetches the
    in-flight page rather than skipping it — the merge dedupes the re-pulled rows on the primary key.
    """
    cursor = start_cursor
    while True:
        data = _fetch_page(session, _build_url(path, cursor), logger)
        items = data.get("data", []) or []

        if items:
            yield items

        # The API always returns a `cursor`, but only `has_more` tells us another page exists.
        next_cursor = data.get("cursor") if data.get("has_more") else None
        if not next_cursor:
            break
        manager.save_state(BigMailerResumeConfig(cursor=next_cursor, brand_id=brand_id))
        cursor = next_cursor


def _iter_brand_ids(session: requests.Session, logger: FilteringBoundLogger) -> Iterator[str]:
    """Page through /brands and yield each brand id, for fanning out brand-scoped endpoints."""
    cursor: str | None = None
    while True:
        data = _fetch_page(session, _build_url("/brands", cursor), logger)
        for item in data.get("data", []) or []:
            yield item["id"]
        cursor = data.get("cursor") if data.get("has_more") else None
        if not cursor:
            break


def _get_top_level_rows(
    session: requests.Session,
    config: BigMailerEndpointConfig,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[BigMailerResumeConfig],
) -> Iterator[list[dict]]:
    resume = manager.load_state() if manager.can_resume() else None
    start_cursor = resume.cursor if resume else None
    yield from _iter_pages(session, config.path, logger, manager, start_cursor, brand_id=None)


def _get_brand_scoped_rows(
    session: requests.Session,
    config: BigMailerEndpointConfig,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[BigMailerResumeConfig],
) -> Iterator[list[dict]]:
    """Fan out a brand-scoped endpoint over every brand, injecting `brand_id` into each row.

    Child objects (lists, segments, campaigns, …) don't carry their brand id in the response, so we
    add it here to keep the composite ["brand_id", "id"] key unique across the whole table.
    """
    brand_ids = list(_iter_brand_ids(session, logger))

    # Resolve the saved brand-ID bookmark to the slice of brands still to process. If the bookmarked
    # brand no longer exists (deleted between runs), start over — merge dedupes the re-pulled rows.
    resume = manager.load_state() if manager.can_resume() else None
    remaining = brand_ids
    resume_cursor: str | None = None
    if resume is not None and resume.brand_id is not None and resume.brand_id in brand_ids:
        remaining = brand_ids[brand_ids.index(resume.brand_id) :]
        resume_cursor = resume.cursor
        logger.debug(f"BigMailer: resuming {config.name} from brand_id={resume.brand_id}, cursor={resume_cursor}")

    for index, brand_id in enumerate(remaining):
        path = config.path.format(brand_id=brand_id)
        start_cursor = resume_cursor  # only the resumed-into brand uses the saved cursor
        resume_cursor = None

        for items in _iter_pages(session, path, logger, manager, start_cursor, brand_id=brand_id):
            yield [{**item, "brand_id": brand_id} for item in items]

        # Advance the bookmark to the next brand so a crash between brands resumes correctly. Its first
        # page is fetched fresh (cursor=None).
        if index + 1 < len(remaining):
            manager.save_state(BigMailerResumeConfig(cursor=None, brand_id=remaining[index + 1]))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[BigMailerResumeConfig],
) -> Iterator[list[dict]]:
    config = BIGMAILER_ENDPOINTS[endpoint]
    # One session reused across every page (and every brand, for fan-out) so urllib3 keeps the
    # connection alive instead of re-handshaking per request. The api key is redacted from logged URLs.
    session = make_tracked_session(headers=_get_headers(api_key), redact_values=(api_key,))

    if config.brand_scoped:
        yield from _get_brand_scoped_rows(session, config, logger, manager)
    else:
        yield from _get_top_level_rows(session, config, logger, manager)


def validate_credentials(api_key: str) -> bool:
    """Cheap probe that the key is genuine. /brands is account-wide and always reachable for a valid
    key, so a 200 confirms the credential without needing any specific brand or scope."""
    try:
        session = make_tracked_session(headers=_get_headers(api_key), redact_values=(api_key,))
        response = session.get(_build_url("/brands", cursor=None), timeout=REQUEST_TIMEOUT_SECONDS)
        return response.status_code == 200
    except Exception:
        return False


def bigmailer_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[BigMailerResumeConfig],
) -> SourceResponse:
    config = BIGMAILER_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(api_key=api_key, endpoint=endpoint, logger=logger, manager=manager),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
    )
