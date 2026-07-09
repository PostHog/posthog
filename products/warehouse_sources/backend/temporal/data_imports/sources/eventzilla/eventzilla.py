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
from products.warehouse_sources.backend.temporal.data_imports.sources.eventzilla.settings import (
    EVENTZILLA_ENDPOINTS,
    EventzillaEndpointConfig,
)

EVENTZILLA_BASE_URL = "https://www.eventzillaapi.net/api/v2"

# Documented default limit is 20; we request a larger page to cut request count. We advance the
# offset by the number of rows actually returned (never a fixed step), so a server that silently
# clamps the page size can't cause us to skip rows.
PAGE_SIZE = 100

# Safety ceiling on pages per list to bound a runaway paginator (e.g. an endpoint that ignores
# offset). Real lists terminate far below this on an empty page.
MAX_PAGES = 10_000


class EventzillaRetryableError(Exception):
    pass


@dataclasses.dataclass
class EventzillaResumeConfig:
    # Offset of the next page to fetch within the current list.
    offset: int = 0
    # For fan-out endpoints, the event whose child list we're currently paging. A stable event-id
    # bookmark (not a positional index) so events added/removed between a crash and the retry can't
    # resume us into the wrong event. None for top-level (non-fan-out) endpoints.
    event_id: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {"x-api-key": api_key, "Accept": "application/json"}


def _build_url(path: str, offset: int) -> str:
    query = urlencode({"offset": offset, "limit": PAGE_SIZE})
    return f"{EVENTZILLA_BASE_URL}{path}?{query}"


@retry(
    retry=retry_if_exception_type(
        (
            EventzillaRetryableError,
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
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise EventzillaRetryableError(f"Eventzilla API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Eventzilla API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> bool:
    # A single cheap probe against the events list confirms the key is genuine without touching
    # any per-event resource (the user may not have events yet).
    url = _build_url("/events", offset=0)
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _iter_pages(
    session: requests.Session,
    path: str,
    data_key: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    start_offset: int = 0,
) -> Iterator[tuple[list[dict[str, Any]], int]]:
    """Page through a limit/offset list, yielding (items, next_offset) per page.

    The response's `pagination` object is the paginate signal: the list endpoints that support
    offset/limit paging (events, users, transactions) return it, so we advance until its `total` is
    reached (or an empty page). Endpoints that return their full result set in one response
    (categories, tickets, and the per-event attendees/tickets samples) omit it, so we stop after the
    first page rather than blindly re-requesting — which could loop forever on an offset-ignoring
    endpoint. Advancing by the real returned count keeps us correct even if the server clamps the
    requested page size.
    """
    offset = start_offset
    for _ in range(MAX_PAGES):
        data = _fetch_page(session, _build_url(path, offset), headers, logger)
        items = data.get(data_key) or []
        if not items:
            return

        offset += len(items)
        yield items, offset

        pagination = data.get("pagination")
        if not isinstance(pagination, dict):
            return
        total = pagination.get("total")
        if total is not None and offset >= total:
            return

    logger.warning(f"Eventzilla: hit MAX_PAGES paging {path}; stopping to avoid a runaway scan")


def _iter_event_ids(session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger) -> list[str]:
    event_ids: list[str] = []
    for items, _ in _iter_pages(session, "/events", "events", headers, logger):
        # `id` is the event primary key; a response missing it is malformed, so fail loudly
        # (KeyError) rather than silently dropping the event and its entire fan-out subtree.
        event_ids.extend(str(item["id"]) for item in items)
    return event_ids


def _get_top_level_rows(
    session: requests.Session,
    config: EventzillaEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[EventzillaResumeConfig],
) -> Iterator[Any]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_offset = resume.offset if resume is not None and resume.event_id is None else 0
    if start_offset:
        logger.debug(f"Eventzilla: resuming {config.name} from offset={start_offset}")

    for items, next_offset in _iter_pages(session, config.path, config.data_key, headers, logger, start_offset):
        for item in items:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                # Save AFTER yielding so a crash re-yields the last page rather than skipping it —
                # merge dedupes on the primary key.
                resumable_source_manager.save_state(EventzillaResumeConfig(offset=next_offset))


def _get_fan_out_rows(
    session: requests.Session,
    config: EventzillaEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[EventzillaResumeConfig],
) -> Iterator[Any]:
    event_ids = _iter_event_ids(session, headers, logger)

    # Resolve the saved event-id bookmark to the slice of events still to process. If the bookmarked
    # event no longer exists (deleted between runs), start over — merge dedupes the re-pulled rows.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = event_ids
    resume_offset = 0
    if resume is not None and resume.event_id is not None and resume.event_id in event_ids:
        remaining = event_ids[event_ids.index(resume.event_id) :]
        resume_offset = resume.offset
        logger.debug(f"Eventzilla: resuming {config.name} from event_id={resume.event_id}, offset={resume_offset}")

    for index, event_id in enumerate(remaining):
        path = config.path.replace("{event_id}", event_id)
        start_offset = resume_offset if index == 0 else 0

        try:
            for items, next_offset in _iter_pages(session, path, config.data_key, headers, logger, start_offset):
                for item in items:
                    item["event_id"] = event_id
                    batcher.batch(item)
                    if batcher.should_yield():
                        yield batcher.get_table()
                        resumable_source_manager.save_state(
                            EventzillaResumeConfig(offset=next_offset, event_id=event_id)
                        )
        except requests.HTTPError as exc:
            # An event deleted between enumeration and this fetch 404s. Skip it rather than failing
            # the whole sync — the child rows are genuinely gone. Any other HTTP error is re-raised.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Eventzilla: event {event_id} not found while fetching {config.name}, skipping")
            else:
                raise

        # Advance the bookmark to the next event so a crash between events resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(EventzillaResumeConfig(offset=0, event_id=remaining[index + 1]))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[EventzillaResumeConfig],
) -> Iterator[Any]:
    config = EVENTZILLA_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # One session reused across every page (and, for fan-out, every event) so urllib3 keeps the
    # connection alive instead of re-handshaking per request.
    session = make_tracked_session()

    if config.fan_out_over_events:
        yield from _get_fan_out_rows(session, config, headers, logger, batcher, resumable_source_manager)
    else:
        yield from _get_top_level_rows(session, config, headers, logger, batcher, resumable_source_manager)

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def eventzilla_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[EventzillaResumeConfig],
) -> SourceResponse:
    endpoint_config = EVENTZILLA_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
