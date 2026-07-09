"""Postmark (ActiveCampaign) transactional email source.

Postmark exposes a REST/JSON API at https://api.postmarkapp.com. Server-level resources
(messages, bounces, templates, message streams) authenticate with a per-server token sent
in the `X-Postmark-Server-Token` header.

Sync is full-refresh only. Postmark's list endpoints accept `fromdate`/`todate` filters
(date granularity, `YYYY-MM-DD`), but we have not been able to verify server-side filtering
against a live token, so we do not advertise incremental sync — matching how the existing
third-party connectors (Airbyte, Fivetran) treat Postmark. Within a sync, pagination is
resumable via the saved offset.

Two upstream constraints worth knowing about:
- The paginated list endpoints cap `count + offset` at 10,000, so a full refresh can only
  reach the most recent 10,000 rows of each. We log a warning when that window is hit.
- Messages expire from Postmark after a retention window (45 days by default), so historical
  data beyond that window is simply unavailable from the API.
"""

import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.postmark.settings import (
    POSTMARK_ENDPOINTS,
    POSTMARK_MAX_PAGE_SIZE,
    POSTMARK_MAX_WINDOW,
    PostmarkEndpointConfig,
)

POSTMARK_BASE_URL = "https://api.postmarkapp.com"


class PostmarkRetryableError(Exception):
    pass


@dataclasses.dataclass
class PostmarkResumeConfig:
    # Offset of the next page to fetch on paginated list endpoints.
    next_offset: int = 0


def _get_headers(server_token: str) -> dict[str, str]:
    return {
        "X-Postmark-Server-Token": server_token,
        "Accept": "application/json",
    }


def validate_credentials(server_token: str) -> bool:
    # /message-streams is a cheap read-only call any valid server token can make. Postmark
    # returns 401 (ErrorCode 10) for an invalid/missing token and 200 otherwise.
    url = f"{POSTMARK_BASE_URL}/message-streams"
    try:
        # `X-Postmark-Server-Token` is not in the sample-capture header denylist, so mask the
        # token by value to keep it out of any captured HTTP sample.
        session = make_tracked_session(headers=_get_headers(server_token), redact_values=(server_token,))
        response = session.get(url, timeout=10)
        return response.status_code == 200
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type((PostmarkRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict:
    response = session.get(url, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise PostmarkRetryableError(f"Postmark API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Postmark API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _iter_flat_endpoint(
    session: requests.Session,
    config: PostmarkEndpointConfig,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Fetch a list endpoint that returns its whole payload in a single response."""
    url = f"{POSTMARK_BASE_URL}{config.path}"
    data = _fetch(session, url, logger)
    items = data.get(config.data_key) or []
    if items:
        yield items


def _iter_paginated_endpoint(
    session: requests.Session,
    config: PostmarkEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PostmarkResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Iterate a list endpoint with Postmark's offset/count pagination (max 10,000 window)."""
    page_size = min(config.page_size or POSTMARK_MAX_PAGE_SIZE, POSTMARK_MAX_PAGE_SIZE)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset: int = resume_config.next_offset if resume_config else 0
    if offset:
        logger.debug(f"Postmark: resuming {config.name} from offset={offset}")

    while offset < POSTMARK_MAX_WINDOW:
        count = min(page_size, POSTMARK_MAX_WINDOW - offset)
        query = urlencode({"count": count, "offset": offset})
        url = f"{POSTMARK_BASE_URL}{config.path}?{query}"

        data = _fetch(session, url, logger)
        items = data.get(config.data_key) or []

        if items:
            yield items

        # A short page means we've reached the end of the available rows.
        if len(items) < count:
            break

        # Advance before the next fetch, then persist so a crash resumes at the next page
        # rather than re-scanning from the start (merge dedupes the re-yielded boundary).
        offset += count
        resumable_source_manager.save_state(PostmarkResumeConfig(next_offset=offset))

        if offset >= POSTMARK_MAX_WINDOW:
            total = data.get("TotalCount")
            logger.warning(
                f"Postmark: reached the {POSTMARK_MAX_WINDOW}-row API window for {config.name} "
                f"(TotalCount={total}); older rows cannot be synced via this endpoint."
            )


def get_rows(
    server_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PostmarkResumeConfig],
) -> Iterator[Any]:
    config = POSTMARK_ENDPOINTS[endpoint]

    # Align the batcher chunk size with the page size for paginated endpoints so each page
    # yields its own table before we persist the resume offset for the next page. With a
    # larger chunk size, several pages would buffer in memory while the offset advances, and
    # a mid-buffer failure could resume past rows that were never yielded — a silent data gap.
    chunk_size = config.page_size or 2000
    batcher = Batcher(logger=logger, chunk_size=chunk_size, chunk_size_bytes=100 * 1024 * 1024)

    # One tracked session for the whole sync — keeps urllib3's TLS connection warm across
    # pages, and every request inherits the auth headers. The server token is also masked by
    # value since `X-Postmark-Server-Token` is not in the sample-capture header denylist.
    session = make_tracked_session(headers=_get_headers(server_token), redact_values=(server_token,))

    if config.page_size is None:
        source_iter = _iter_flat_endpoint(session, config, logger)
    else:
        source_iter = _iter_paginated_endpoint(session, config, logger, resumable_source_manager)

    for batch in source_iter:
        batcher.batch(batch)
        if batcher.should_yield():
            yield batcher.get_table()

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def postmark_source(
    server_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PostmarkResumeConfig],
) -> SourceResponse:
    endpoint_config = POSTMARK_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            server_token=server_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=[endpoint_config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
