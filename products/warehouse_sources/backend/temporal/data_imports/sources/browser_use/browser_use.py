import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.browser_use.settings import (
    BROWSER_USE_ENDPOINTS,
    BrowserUseEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

BROWSER_USE_BASE_URL = "https://api.browser-use.com/api/v3"
API_KEY_HEADER = "X-Browser-Use-API-Key"
REQUEST_TIMEOUT_SECONDS = 60


class BrowserUseRetryableError(Exception):
    pass


@dataclasses.dataclass
class BrowserUseResumeConfig:
    # Next 1-indexed page/pageNumber to fetch for a top-level list endpoint. None for fan-out.
    page: int | None = None
    # Fan-out (session_messages): the session currently being read. A stable session id (not a
    # positional index) so sessions added/removed between a crash and the retry can't resume us
    # into the wrong session.
    session_id: str | None = None
    # Fan-out: the `after` message-id cursor within the current session.
    after: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {API_KEY_HEADER: api_key, "Accept": "application/json"}


def _build_url(path: str, params: dict[str, Any]) -> str:
    url = f"{BROWSER_USE_BASE_URL}{path}"
    clean = {k: v for k, v in params.items() if v is not None}
    return f"{url}?{urlencode(clean)}" if clean else url


@retry(
    retry=retry_if_exception_type(
        (
            BrowserUseRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise BrowserUseRetryableError(f"Browser Use API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Log status + URL only. Error bodies can echo prompt/message content or other tenant data,
        # which must not land in application logs outside warehouse-table access controls.
        logger.error(f"Browser Use API error: status={response.status_code}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> bool:
    # The cheapest genuine token probe: list a single session. 200 means the key is accepted.
    url = _build_url("/sessions", {"page_size": 1})
    try:
        # capture=False: the probe lists a session, whose body carries the same free-form agent
        # content as the export bodies below — keep it out of HTTP sample capture.
        # allow_redirects=False: the API key rides in a custom header that `requests` preserves
        # across cross-host 3xx (it only strips `Authorization`), so pin redirects off to keep the
        # key from replaying to a redirect target. The fixed API host never needs redirects.
        response = make_tracked_session(redact_values=(api_key,), capture=False, allow_redirects=False).get(
            url, headers=_get_headers(api_key), timeout=10
        )
        return response.status_code == 200
    except Exception:
        return False


def _page_params(config: BrowserUseEndpointConfig, page: int) -> dict[str, Any]:
    if config.pagination == "page":
        return {"page": page, "page_size": config.page_size}
    return {"pageNumber": page, "pageSize": config.page_size}


def _get_paged_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BrowserUseResumeConfig],
    config: BrowserUseEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume is not None and resume.page else 1

    while True:
        data = _fetch_page(session, _build_url(config.path, _page_params(config, page)), headers, logger)
        items = data.get(config.data_key) or []
        if not items:
            break

        yield items

        # `total`/`totalItems` gives an exact stopping point; without it, a short page (fewer rows
        # than requested) means we've reached the end. Save AFTER yielding so a crash re-yields the
        # last page rather than skipping it (merge dedupes on the primary key).
        total = data.get("total") if config.pagination == "page" else data.get("totalItems")
        if total is not None:
            has_more = page * config.page_size < total
        else:
            has_more = len(items) >= config.page_size

        if not has_more:
            break

        page += 1
        resumable_source_manager.save_state(BrowserUseResumeConfig(page=page))


def _iter_session_ids(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[str]:
    page = 1
    while True:
        data = _fetch_page(session, _build_url("/sessions", {"page": page, "page_size": 100}), headers, logger)
        sessions = data.get("sessions") or []
        if not sessions:
            break

        for item in sessions:
            yield item["id"]

        total = data.get("total")
        if total is not None:
            if page * 100 >= total:
                break
        elif len(sessions) < 100:
            break

        page += 1


def _get_session_message_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BrowserUseResumeConfig],
    config: BrowserUseEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    session_ids = list(_iter_session_ids(session, headers, logger))

    # Resume only fast-forwards the message cursor *within* the session that was mid-read at the
    # crash; we deliberately re-walk every session rather than slicing the list from the bookmark.
    # The API guarantees no session ordering, so a session that reorders (or is newly inserted)
    # ahead of the bookmark between runs would be skipped for the whole resumed run if we sliced.
    # Re-pulling already-synced sessions is cheap correctness insurance — merge dedupes the rows on
    # the [sessionId, id] primary key.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    resume_session_id = resume.session_id if resume is not None else None
    resume_after = resume.after if resume is not None else None
    if resume_session_id is not None:
        logger.debug(f"Browser Use: resuming session_messages cursor within session_id={resume_session_id}")

    for index, session_id in enumerate(session_ids):
        # Only the bookmarked session continues from its saved cursor; every other session restarts.
        after = resume_after if session_id == resume_session_id else None
        path = config.path.format(session_id=session_id)

        while True:
            data = _fetch_page(session, _build_url(path, {"after": after, "limit": config.page_size}), headers, logger)
            messages = data.get(config.data_key) or []
            if messages:
                # Stamp the parent session id: the child endpoint may omit it from each message, but
                # it's half of the declared [sessionId, id] primary key, so the merge needs it present.
                yield [{**message, "sessionId": session_id} for message in messages]

            has_more = bool(data.get("hasMore")) and bool(messages)
            if not has_more:
                break

            after = messages[-1]["id"]
            resumable_source_manager.save_state(BrowserUseResumeConfig(session_id=session_id, after=after))

        # Advance the bookmark to the next session so a crash between sessions resumes correctly.
        if index + 1 < len(session_ids):
            resumable_source_manager.save_state(BrowserUseResumeConfig(session_id=session_ids[index + 1], after=None))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BrowserUseResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = BROWSER_USE_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across every page (and, for fan-out, every child request) so urllib3 keeps
    # the connection alive instead of re-handshaking per request. Register the key for redaction so
    # the shared HTTP observer masks it anywhere it surfaces in captured URLs or samples.
    # capture=False: session titles and session_messages.data hold arbitrary user/agent content the
    # name-based scrubbers can't recognise, so exclude the bodies from HTTP sample capture entirely.
    # allow_redirects=False: the API key rides in a custom header that `requests` preserves across
    # cross-host 3xx, so pin redirects off to keep it from replaying to a redirect target.
    session = make_tracked_session(redact_values=(api_key,), capture=False, allow_redirects=False)

    if config.fan_out_over_sessions:
        yield from _get_session_message_rows(session, headers, logger, resumable_source_manager, config)
    else:
        yield from _get_paged_rows(session, headers, logger, resumable_source_manager, config)


def browser_use_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BrowserUseResumeConfig],
) -> SourceResponse:
    config = BROWSER_USE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        # Full-refresh endpoints with no guaranteed API ordering; the watermark is not used, but
        # the batches arrive oldest-first within each page so "asc" is the honest default.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
