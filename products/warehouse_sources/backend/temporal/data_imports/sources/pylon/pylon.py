import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.pylon.settings import (
    ISSUES_MAX_WINDOW_DAYS,
    PYLON_ENDPOINTS,
    PylonEndpointConfig,
)

PYLON_BASE_URL = "https://api.usepylon.com"


class PylonRetryableError(Exception):
    pass


@dataclasses.dataclass
class PylonResumeConfig:
    # Next-page cursor within the current page scroll.
    cursor: str | None = None
    # RFC3339 start of the issues window currently being processed (windowed endpoints only).
    window_start: str | None = None
    # The custom-fields object_type currently being fanned out (fan-out endpoints only).
    object_type: str | None = None


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _format_rfc3339(dt: datetime) -> str:
    """Pylon's time-window params expect RFC3339. Use the Z suffix rather than +00:00."""
    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_rfc3339(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _to_datetime(value: Any) -> datetime:
    """Coerce an incremental cursor value (datetime / date / RFC3339 string) to an aware datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    return _parse_rfc3339(str(value))


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


@retry(
    retry=retry_if_exception_type((PylonRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=60)

    # Pylon enforces tight per-endpoint rate limits (e.g. 10 req/min on /issues); back off and retry on
    # 429 and transient 5xx. Everything else (notably 401/403) raises immediately so the sync surfaces a
    # non-retryable credential error rather than spinning.
    if response.status_code == 429 or response.status_code >= 500:
        raise PylonRetryableError(f"Pylon API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Pylon API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_token: str) -> bool:
    try:
        # redact_values masks the bearer token in logs/sample capture; allow_redirects=False keeps the
        # credentialed request from following an off-origin redirect that could leak the token.
        session = make_tracked_session(redact_values=(api_token,), allow_redirects=False)
        response = session.get(f"{PYLON_BASE_URL}/me", headers=_get_headers(api_token), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _iter_pages(
    session: requests.Session,
    headers: dict[str, str],
    path: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
    start_cursor: str | None = None,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    """Page through a Pylon list endpoint, yielding (items, next_cursor) per page.

    `next_cursor` is the cursor to fetch the page *after* the one just yielded, or None when the API
    signals no further pages. Endpoints that return no `pagination` object (e.g. macros) yield exactly
    one page with `next_cursor=None`.
    """
    cursor = start_cursor
    seen_cursors: set[str] = set()
    while True:
        page_params = dict(params)
        if cursor:
            page_params["cursor"] = cursor

        data = _fetch_page(session, _build_url(f"{PYLON_BASE_URL}{path}", page_params), headers, logger)
        items = data.get("data") or []
        pagination = data.get("pagination") or {}
        next_cursor = pagination.get("cursor") if pagination.get("has_next_page") else None

        yield items, next_cursor

        if not next_cursor:
            break
        # A few list endpoints don't document the cursor param; guard against an endpoint that keeps
        # reporting has_next_page with a cursor it then ignores, which would otherwise loop forever on
        # the same page.
        if next_cursor in seen_cursors:
            logger.warning(f"Pylon: cursor did not advance for {path}, stopping pagination")
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor


def _get_simple_rows(
    session: requests.Session,
    headers: dict[str, str],
    config: PylonEndpointConfig,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[PylonResumeConfig],
    resume: PylonResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    params: dict[str, Any] = {}
    if config.limit:
        params["limit"] = config.limit

    start_cursor = resume.cursor if resume else None
    for items, next_cursor in _iter_pages(session, headers, config.path, params, logger, start_cursor):
        if items:
            yield items
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it; merge dedupes
        # on the primary key.
        if next_cursor:
            manager.save_state(PylonResumeConfig(cursor=next_cursor))


def _get_fan_out_rows(
    session: requests.Session,
    headers: dict[str, str],
    config: PylonEndpointConfig,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[PylonResumeConfig],
    resume: PylonResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    object_types = config.fan_out_object_types or []

    remaining = object_types
    resume_cursor: str | None = None
    if resume is not None and resume.object_type is not None and resume.object_type in object_types:
        remaining = object_types[object_types.index(resume.object_type) :]
        resume_cursor = resume.cursor

    for index, object_type in enumerate(remaining):
        params: dict[str, Any] = {"object_type": object_type}
        if config.limit:
            params["limit"] = config.limit

        start_cursor = resume_cursor if index == 0 else None
        resume_cursor = None

        for items, next_cursor in _iter_pages(session, headers, config.path, params, logger, start_cursor):
            # Stamp the queried object_type so a single table covers every type and the composite
            # [object_type, id] primary key stays unique even if two types reuse an id.
            stamped = [{**item, "object_type": item.get("object_type") or object_type} for item in items]
            if stamped:
                yield stamped
            if next_cursor:
                manager.save_state(PylonResumeConfig(cursor=next_cursor, object_type=object_type))

        # Advance the bookmark to the next object_type so a crash between types resumes correctly.
        if index + 1 < len(remaining):
            manager.save_state(PylonResumeConfig(cursor=None, object_type=remaining[index + 1]))


def _get_windowed_rows(
    session: requests.Session,
    headers: dict[str, str],
    config: PylonEndpointConfig,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[PylonResumeConfig],
    resume: PylonResumeConfig | None,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Walk `/issues` forward one <=30-day window at a time.

    The endpoint requires a start_time/end_time window no longer than 30 days, so a backfill is a
    sequence of ascending windows ending at "now". On an incremental run we start from the saved
    watermark; on a first sync we look back `default_lookback_days`. Windows are processed strictly
    ascending and always extended up to "now", so the resumable state (exact window + cursor) and the
    incremental watermark both pick back up without gaps regardless of intra-window ordering.
    """
    now = datetime.now(UTC)

    if should_use_incremental_field and db_incremental_field_last_value:
        overall_start = _to_datetime(db_incremental_field_last_value)
    else:
        lookback_days = config.default_lookback_days or ISSUES_MAX_WINDOW_DAYS
        overall_start = now - timedelta(days=lookback_days)

    # A future-dated watermark would make every window empty; cap it so the sync stays a no-op rather
    # than building an invalid window.
    overall_start = min(overall_start, now)

    if resume is not None and resume.window_start:
        window_start = _parse_rfc3339(resume.window_start)
        resume_cursor = resume.cursor
    else:
        window_start = overall_start
        resume_cursor = None

    while window_start < now:
        window_end = min(window_start + timedelta(days=ISSUES_MAX_WINDOW_DAYS), now)
        params: dict[str, Any] = {
            "start_time": _format_rfc3339(window_start),
            "end_time": _format_rfc3339(window_end),
        }
        if config.limit:
            params["limit"] = config.limit

        start_cursor = resume_cursor
        resume_cursor = None

        for items, next_cursor in _iter_pages(session, headers, config.path, params, logger, start_cursor):
            if items:
                yield items
            if next_cursor:
                manager.save_state(PylonResumeConfig(cursor=next_cursor, window_start=params["start_time"]))

        window_start = window_end
        if window_start < now:
            manager.save_state(PylonResumeConfig(cursor=None, window_start=_format_rfc3339(window_start)))


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PylonResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = PYLON_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)
    # redact_values masks the bearer token in logs/sample capture; allow_redirects=False keeps the
    # credentialed request from following an off-origin redirect that could leak the token.
    session = make_tracked_session(redact_values=(api_token,), allow_redirects=False)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.windowed:
        yield from _get_windowed_rows(
            session,
            headers,
            config,
            logger,
            resumable_source_manager,
            resume,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    elif config.fan_out_object_types:
        yield from _get_fan_out_rows(session, headers, config, logger, resumable_source_manager, resume)
    else:
        yield from _get_simple_rows(session, headers, config, logger, resumable_source_manager, resume)


def pylon_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PylonResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = PYLON_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Issues windows are processed strictly ascending; the other endpoints are full-refresh cursor
        # scrolls where sort_mode is not used to checkpoint a watermark.
        sort_mode="asc",
    )
