import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.zep.settings import (
    ZEP_BASE_URL,
    ZEP_ENDPOINTS,
    ZepEndpointConfig,
)

# Zep's rate limits are plan-based and undocumented, so we lean on retries with backoff and honor
# any Retry-After the API sends on a 429.
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5


class ZepRetryableError(Exception):
    pass


@dataclasses.dataclass
class ZepResumeConfig:
    # Page-based endpoints (users, threads): the next 1-based page to fetch.
    page_number: int | None = None
    # thread_messages fan-out: the thread we were part-way through and the message cursor
    # (offset) to resume it at. `thread_id` is a stable id (not a positional index) so threads
    # added/removed between a crash and the retry can't resume us into the wrong thread.
    thread_id: str | None = None
    cursor: int | None = None


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Api-Key {api_key}",
        "Accept": "application/json",
    }


def _build_url(path: str, params: dict[str, Any]) -> str:
    url = f"{ZEP_BASE_URL}{path}"
    if not params:
        return url
    return f"{url}?{urlencode(params)}"


@retry(
    retry=retry_if_exception_type(
        (
            ZepRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise ZepRetryableError(f"Zep API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Zep API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> bool:
    # A single cheap probe: 200 means the key is genuine. Any non-200 (401 "unauthorized" for a
    # bad key) means invalid. Never raises; network blips fall through to False.
    url = _build_url("/users-ordered", {"pageSize": 1})
    try:
        response = make_tracked_session().get(url, headers=_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _page_based_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZepResumeConfig],
    config: ZepEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    """Walk a page-numbered endpoint (users, threads), yielding one page of rows at a time."""
    assert config.page_number_param is not None and config.page_size_param is not None

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page_number = resume.page_number if resume is not None and resume.page_number else 1

    seen = 0
    while True:
        params: dict[str, Any] = {
            config.page_size_param: config.page_size,
            config.page_number_param: page_number,
        }
        if config.order_by:
            params["order_by"] = config.order_by
            # Ascending (oldest-first) so the order matches SourceResponse.sort_mode="asc".
            params["asc"] = "true"

        data = _fetch_page(session, _build_url(config.path, params), headers, logger)
        items = data.get(config.data_key) or []
        if not items:
            break

        yield items
        seen += len(items)

        total_count = data.get("total_count")
        # A short page or reaching the reported total means the last page has been served.
        if (total_count is not None and seen >= total_count) or len(items) < config.page_size:
            break

        page_number += 1
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it; merge
        # dedupes the re-pulled rows on the primary key.
        resumable_source_manager.save_state(ZepResumeConfig(page_number=page_number))


def _iter_thread_ids(session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger) -> list[str]:
    """Enumerate every thread id by paging /threads (used to fan out into per-thread messages)."""
    threads_config = ZEP_ENDPOINTS["threads"]
    thread_ids: list[str] = []
    page_number = 1
    while True:
        params: dict[str, Any] = {
            "page_size": threads_config.page_size,
            "page_number": page_number,
            "order_by": "created_at",
            "asc": "true",
        }
        data = _fetch_page(session, _build_url("/threads", params), headers, logger)
        items = data.get("threads") or []
        if not items:
            break
        thread_ids.extend(item["thread_id"] for item in items if item.get("thread_id"))
        total_count = data.get("total_count")
        if (total_count is not None and len(thread_ids) >= total_count) or len(items) < threads_config.page_size:
            break
        page_number += 1
    return thread_ids


def _fan_out_message_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZepResumeConfig],
    config: ZepEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every thread, yielding its messages enriched with the parent thread id.

    Messages paginate with an integer `cursor`. The API documents `cursor` only as "Cursor for
    pagination" with no next-cursor field in the response, so we treat it as an offset (advance by
    the number of rows returned) and stop once a short page or the reported total is reached. If Zep
    ever changes cursor semantics this stays safe: merge dedupes on the message `uuid` primary key.
    """
    thread_ids = _iter_thread_ids(session, headers, logger)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = thread_ids
    resume_cursor: int | None = None
    if resume is not None and resume.thread_id is not None and resume.thread_id in thread_ids:
        remaining = thread_ids[thread_ids.index(resume.thread_id) :]
        resume_cursor = resume.cursor
        logger.debug(f"Zep: resuming thread_messages from thread_id={resume.thread_id}, cursor={resume_cursor}")

    for index, thread_id in enumerate(remaining):
        path = config.path.format(thread_id=thread_id)
        cursor = resume_cursor or 0
        resume_cursor = None  # only the resumed-into thread uses the saved cursor

        seen = 0
        while True:
            params: dict[str, Any] = {"limit": config.page_size}
            if cursor:
                params["cursor"] = cursor

            data = _fetch_page(session, _build_url(path, params), headers, logger)
            items = data.get(config.data_key) or []
            if not items:
                break

            user_id = data.get("user_id")
            rows = [{**item, "thread_id": thread_id, "user_id": user_id} for item in items]
            yield rows

            seen += len(items)
            cursor += len(items)

            total_count = data.get("total_count")
            if (total_count is not None and seen >= total_count) or len(items) < config.page_size:
                break

            # Save mid-thread progress after yielding, so a crash resumes this thread at the cursor.
            resumable_source_manager.save_state(ZepResumeConfig(thread_id=thread_id, cursor=cursor))

        # Advance the bookmark to the next thread so a crash between threads resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(ZepResumeConfig(thread_id=remaining[index + 1], cursor=0))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZepResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = ZEP_ENDPOINTS[endpoint]
    headers = _headers(api_key)
    # One session reused across every page (and, for the fan-out, every thread) so urllib3 keeps
    # the connection alive instead of re-handshaking per request.
    session = make_tracked_session()

    if config.fan_out_over_threads:
        yield from _fan_out_message_rows(session, headers, logger, resumable_source_manager, config)
    else:
        yield from _page_based_rows(session, headers, logger, resumable_source_manager, config)


def zep_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZepResumeConfig],
) -> SourceResponse:
    config = ZEP_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        # Rows arrive oldest-first (created_at ascending / message cursor order).
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


__all__ = ["ZepResumeConfig", "get_rows", "validate_credentials", "zep_source"]
