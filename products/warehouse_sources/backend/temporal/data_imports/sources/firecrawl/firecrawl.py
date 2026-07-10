import dataclasses
from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.firecrawl.settings import (
    FIRECRAWL_BASE_URL,
    FIRECRAWL_ENDPOINTS,
    FirecrawlEndpointConfig,
)

# Both the cursor endpoint (activity) and the offset endpoints (monitors, monitor checks) cap page
# size at 100. Ask for the maximum to minimize round trips.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Hard stop so a misbehaving offset endpoint (one that never shrinks a page below PAGE_SIZE) can't
# spin forever. 100 * 100_000 = 10M rows per resource, far above any realistic account.
MAX_PAGE_ITERATIONS = 100_000


class FirecrawlRetryableError(Exception):
    pass


@dataclasses.dataclass
class FirecrawlResumeConfig:
    # team_activity cursor-pagination bookmark: the cursor for the next page to fetch.
    cursor: str | None = None
    # Offset for the offset-paginated endpoints (monitors, monitor_checks).
    offset: int | None = None
    # monitor_checks fan-out: the monitor whose checks we're currently paging. A stable ID bookmark
    # (not a positional index) so monitors added/removed between a crash and the retry can't resume
    # us into the wrong monitor. None for the non-fan-out endpoints.
    monitor_id: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


@retry(
    # ChunkedEncodingError is a mid-stream connection break (server truncated a chunked body); it's
    # transient like ConnectionError/ReadTimeout but not a ConnectionError subclass, so list it.
    retry=retry_if_exception_type(
        (
            FirecrawlRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    params: dict[str, Any] | None,
    logger: FilteringBoundLogger,
) -> dict:
    response = session.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    # Plan-based rate/concurrency limits surface as 429; 5xx are transient. Back off and retry both.
    if response.status_code == 429 or response.status_code >= 500:
        raise FirecrawlRetryableError(f"Firecrawl API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Firecrawl API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> bool:
    # credit-usage is a cheap, always-present team endpoint: a genuine key returns 200, an invalid or
    # revoked one 401. We only confirm the token itself here (see FirecrawlSource.validate_credentials).
    url = f"{FIRECRAWL_BASE_URL}/v2/team/credit-usage"
    try:
        # Redact the bearer token from tracked logs/samples in case Firecrawl reflects it back
        # (redirect URL, error body, or a non-denylisted field).
        response = make_tracked_session(redact_values=(api_key,)).get(url, headers=_get_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _fetch_single(
    session: requests.Session, headers: dict[str, str], cfg: FirecrawlEndpointConfig, logger: FilteringBoundLogger
) -> list[dict]:
    """Unpaginated endpoints: one request, return the whole row array."""
    data = _fetch(session, f"{FIRECRAWL_BASE_URL}{cfg.path}", headers, None, logger)
    # Index (not .get) so a renamed/missing selector fails the sync loudly instead of silently
    # replacing warehouse data with zero rows on a full refresh.
    return data[cfg.data_selector] or []


def _iter_cursor_pages(
    session: requests.Session,
    headers: dict[str, str],
    cfg: FirecrawlEndpointConfig,
    manager: ResumableSourceManager[FirecrawlResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict]]:
    """Cursor-paginated endpoints (team activity). Yields one page of rows at a time."""
    resume = manager.load_state() if manager.can_resume() else None
    cursor = resume.cursor if resume else None
    if cursor:
        logger.debug(f"Firecrawl: resuming {cfg.name} from cursor")

    url = f"{FIRECRAWL_BASE_URL}{cfg.path}"
    for _ in range(MAX_PAGE_ITERATIONS):
        params: dict[str, Any] = {"limit": PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor
        data = _fetch(session, url, headers, params, logger)

        # Index (not .get) so a renamed/missing selector fails loudly rather than truncating the sync.
        yield data[cfg.data_selector] or []

        next_cursor = data.get("cursor")
        if not data.get("has_more") or not next_cursor:
            break
        cursor = next_cursor
        # Save AFTER yielding the page so a crash resumes at the next page rather than replaying the
        # whole log; full-refresh keeps already-written rows on resume, and the primary key dedupes.
        manager.save_state(FirecrawlResumeConfig(cursor=cursor))


def _iter_offset_pages(
    session: requests.Session,
    headers: dict[str, str],
    path: str,
    data_selector: str,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[FirecrawlResumeConfig] | None = None,
    monitor_id: str | None = None,
    start_offset: int = 0,
) -> Iterator[list[dict]]:
    """Offset-paginated endpoints (monitors, monitor checks). Yields one page of rows at a time.

    Termination is a short page (< PAGE_SIZE): these endpoints return no total or has_more flag, so
    a full page means "there may be more". When a manager is supplied, saves the next offset (and the
    fan-out monitor_id) after each page so a resume picks up mid-resource.
    """
    offset = start_offset
    url = f"{FIRECRAWL_BASE_URL}{path}"
    for _ in range(MAX_PAGE_ITERATIONS):
        data = _fetch(session, url, headers, {"limit": PAGE_SIZE, "offset": offset}, logger)
        # Index (not .get) so a renamed/missing selector fails loudly rather than truncating the sync.
        items = data[data_selector] or []

        yield items

        if len(items) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        if manager is not None:
            manager.save_state(FirecrawlResumeConfig(offset=offset, monitor_id=monitor_id))


def _iter_monitor_ids(session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger) -> list[str]:
    monitor_ids: list[str] = []
    for page in _iter_offset_pages(session, headers, FIRECRAWL_ENDPOINTS["monitors"].path, "data", logger):
        # Index (not a guarded skip) so a monitor row missing its id fails loudly rather than
        # silently dropping every check for that monitor.
        monitor_ids.extend(item["id"] for item in page)
    return monitor_ids


def _iter_monitor_checks(
    session: requests.Session,
    headers: dict[str, str],
    cfg: FirecrawlEndpointConfig,
    manager: ResumableSourceManager[FirecrawlResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict]]:
    """Fan out over every monitor, paging each monitor's checks. Each check id is a globally-unique
    uuid, and every row also carries its `monitorId`, so the primary key stays unique table-wide."""
    monitor_ids = _iter_monitor_ids(session, headers, logger)

    resume = manager.load_state() if manager.can_resume() else None
    remaining = monitor_ids
    resume_offset = 0
    if resume is not None and resume.monitor_id is not None and resume.monitor_id in monitor_ids:
        remaining = monitor_ids[monitor_ids.index(resume.monitor_id) :]
        resume_offset = resume.offset or 0
        logger.debug(f"Firecrawl: resuming monitor_checks from monitor {resume.monitor_id}, offset {resume_offset}")

    for index, monitor_id in enumerate(remaining):
        path = cfg.path.replace("{monitor_id}", monitor_id)
        start_offset = resume_offset if index == 0 else 0
        yield from _iter_offset_pages(
            session,
            headers,
            path,
            cfg.data_selector,
            logger,
            manager=manager,
            monitor_id=monitor_id,
            start_offset=start_offset,
        )
        # Advance the bookmark to the next monitor so a crash between monitors resumes correctly.
        if index + 1 < len(remaining):
            manager.save_state(FirecrawlResumeConfig(offset=0, monitor_id=remaining[index + 1]))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FirecrawlResumeConfig],
) -> Iterator[list[dict]]:
    cfg = FIRECRAWL_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across every page so urllib3 keeps the connection alive. Redact the bearer
    # token from tracked logs/samples in case Firecrawl reflects it back in a URL or response body.
    session = make_tracked_session(redact_values=(api_key,))

    if cfg.fan_out_over_monitors:
        yield from _iter_monitor_checks(session, headers, cfg, resumable_source_manager, logger)
    elif cfg.pagination == "cursor":
        yield from _iter_cursor_pages(session, headers, cfg, resumable_source_manager, logger)
    elif cfg.pagination == "offset":
        yield from _iter_offset_pages(
            session, headers, cfg.path, cfg.data_selector, logger, manager=resumable_source_manager
        )
    else:
        yield _fetch_single(session, headers, cfg, logger)


def firecrawl_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FirecrawlResumeConfig],
) -> SourceResponse:
    cfg = FIRECRAWL_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=cfg.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if cfg.partition_key else None,
        partition_format=cfg.partition_format if cfg.partition_key else None,
        partition_keys=[cfg.partition_key] if cfg.partition_key else None,
    )
