import dataclasses
from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.easypromos.settings import (
    EASYPROMOS_ENDPOINTS,
    EasypromosEndpointConfig,
)

EASYPROMOS_BASE_URL = "https://api.easypromosapp.com/v2"

# Bounded retries for the 200 req/min rate limit (429) and transient 5xx. Tuning kept near the top.
_MAX_RETRY_ATTEMPTS = 6
_REQUEST_TIMEOUT_SECONDS = 60


class EasypromosRetryableError(Exception):
    """A 429 or 5xx that a fresh request can recover from."""


@dataclasses.dataclass
class EasypromosResumeConfig:
    # Cursor that fetched the list page currently being processed. For top-level endpoints this is
    # the endpoint's own page cursor; for fan-out endpoints it's the `/promotions` page cursor.
    # None means the first page. On resume we re-fetch this page and the delta loader dedupes the
    # re-delivered chunk, so no rows are lost or doubled.
    cursor: int | None = None
    # Fan-out only: the promotion whose child rows are currently being emitted, plus the child-list
    # cursor within that promotion. Lets a fan-out sync resume mid-promotion instead of re-walking
    # the whole parent page, so a single huge promotion can't livelock the resume.
    promotion_id: int | None = None
    child_cursor: int | None = None


def _get_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


@retry(
    retry=retry_if_exception_type(
        (EasypromosRetryableError, requests.ReadTimeout, requests.ConnectionError),
    ),
    stop=stop_after_attempt(_MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(url, params=params, headers=headers, timeout=_REQUEST_TIMEOUT_SECONDS)

    # 429 (rate limit) and 5xx are transient — retry with backoff. Easypromos allows 200 req/min
    # per account, so a busy fan-out can legitimately hit the limit.
    if response.status_code == 429 or response.status_code >= 500:
        raise EasypromosRetryableError(f"Easypromos API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Fan-out error bodies can echo PII from the API, so log only a short, truncated prefix
        # rather than the full body.
        body_prefix = response.text[:200]
        logger.error(f"Easypromos API error: status={response.status_code}, body_prefix={body_prefix!r}, url={url}")
        response.raise_for_status()

    data = response.json()
    return data if isinstance(data, dict) else {"items": data}


def _next_cursor(data: dict[str, Any]) -> int | None:
    """Read the cursor for the next page. Easypromos wraps lists as
    `{"items": [...], "paging": {"next_cursor": <int|null>, "items_page": 100}}`; a null
    `next_cursor` marks the last page."""
    paging = data.get("paging")
    if not isinstance(paging, dict):
        return None
    return paging.get("next_cursor")


def _iter_list_pages(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    start_cursor: int | None = None,
) -> Iterator[tuple[list[dict[str, Any]], int | None]]:
    """Yield (items, request_cursor) for each page of an Easypromos list, following `next_cursor`.

    `request_cursor` is the cursor used to FETCH the yielded page (None for the first page), so a
    caller can checkpoint it and, on resume, re-fetch exactly that page.
    """
    cursor = start_cursor
    while True:
        params: dict[str, Any] = {}
        if cursor is not None:
            params["next_cursor"] = cursor
        data = _fetch_page(session, url, params, headers, logger)

        items = data.get("items")
        items = items if isinstance(items, list) else []
        yield items, cursor

        next_cursor = _next_cursor(data)
        if next_cursor is None:
            return
        cursor = next_cursor


def validate_credentials(access_token: str) -> tuple[bool, str | None]:
    """One cheap probe of the account-wide Bearer token against `/promotions`."""
    try:
        with make_tracked_session() as session:
            response = session.get(
                f"{EASYPROMOS_BASE_URL}/promotions",
                headers=_get_headers(access_token),
                timeout=10,
            )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Easypromos access token"
    if response.status_code == 403:
        # Valid token, but the account plan can't reach the REST API (Basic/Premium) or lacks
        # access to this resource. Surface it rather than silently failing.
        return False, "Your Easypromos plan does not have access to the REST API (requires White Label or Corporate)"
    return False, f"Easypromos API returned status {response.status_code}"


def _get_top_level_rows(
    session: requests.Session,
    endpoint_config: EasypromosEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[EasypromosResumeConfig],
) -> Iterator[Any]:
    """Page through a top-level list endpoint (`/promotions`, `/organizing_brands`)."""
    url = f"{EASYPROMOS_BASE_URL}{endpoint_config.path}"

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_cursor = resume.cursor if resume is not None else None

    for items, request_cursor in _iter_list_pages(session, url, headers, logger, start_cursor=start_cursor):
        for item in items:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                # Save AFTER yielding so a crash re-fetches the current page rather than skipping it.
                resumable_source_manager.save_state(EasypromosResumeConfig(cursor=request_cursor))


def _get_fan_out_rows(
    session: requests.Session,
    endpoint_config: EasypromosEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[EasypromosResumeConfig],
) -> Iterator[Any]:
    """Walk `/promotions` and emit child rows for each promotion, injecting `promotion_id` so the
    composite primary key is unique across promotions."""
    promotions_url = f"{EASYPROMOS_BASE_URL}{EASYPROMOS_ENDPOINTS['promotions'].path}"

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    parent_start_cursor = resume.cursor if resume is not None else None
    resume_promotion_id = resume.promotion_id if resume is not None else None
    resume_child_cursor = resume.child_cursor if resume is not None else None

    for promotions, parent_cursor in _iter_list_pages(
        session, promotions_url, headers, logger, start_cursor=parent_start_cursor
    ):
        # When resuming into a parent page, skip the promotions already fully processed before the
        # crash; pick up at the one we were mid-way through.
        skipping = resume_promotion_id is not None
        for promotion in promotions:
            promotion_id = promotion["id"]
            if skipping:
                if promotion_id != resume_promotion_id:
                    continue
                skipping = False

            child_start_cursor = resume_child_cursor if promotion_id == resume_promotion_id else None
            # Consume the saved child cursor only for the promotion it belongs to.
            resume_child_cursor = None

            child_path = endpoint_config.path.format(promotion_id=promotion_id)
            child_url = f"{EASYPROMOS_BASE_URL}{child_path}"

            for items, child_cursor in _iter_list_pages(
                session, child_url, headers, logger, start_cursor=child_start_cursor
            ):
                for item in items:
                    item["promotion_id"] = promotion_id
                    batcher.batch(item)
                    if batcher.should_yield():
                        yield batcher.get_table()
                        # Checkpoint at promotion + child-page granularity so resume makes forward
                        # progress instead of re-fanning the whole parent page.
                        resumable_source_manager.save_state(
                            EasypromosResumeConfig(
                                cursor=parent_cursor,
                                promotion_id=promotion_id,
                                child_cursor=child_cursor,
                            )
                        )
        # A parent page whose promotions we processed without ever resuming has consumed the resume
        # bookmark; clear it so later pages aren't skipped.
        resume_promotion_id = None


def get_rows(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[EasypromosResumeConfig],
) -> Iterator[Any]:
    endpoint_config = EASYPROMOS_ENDPOINTS[endpoint]
    headers = _get_headers(access_token)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # One session reused across every page (and, for fan-out, every promotion) so urllib3 keeps the
    # connection alive instead of re-handshaking per request. The context manager tears down the
    # connection pool even when a request raises mid-stream.
    with make_tracked_session() as session:
        if endpoint_config.fan_out_over_promotions:
            yield from _get_fan_out_rows(session, endpoint_config, headers, logger, batcher, resumable_source_manager)
        else:
            yield from _get_top_level_rows(session, endpoint_config, headers, logger, batcher, resumable_source_manager)

        if batcher.should_yield(include_incomplete_chunk=True):
            yield batcher.get_table()


def easypromos_source(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[EasypromosResumeConfig],
) -> SourceResponse:
    endpoint_config = EASYPROMOS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token=access_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
