import base64
import hashlib
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import orjson
import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.cursor.settings import (
    CURSOR_ENDPOINTS,
    CursorEndpointConfig,
)

CURSOR_BASE_URL = "https://api.cursor.com"

# The windowed endpoints reject date ranges longer than 30 days, so backfills chunk into windows.
MAX_WINDOW_DAYS = 30
# First sync fetches this much history instead of walking back to the team's creation.
DEFAULT_LOOKBACK_DAYS = 365
REQUEST_TIMEOUT_SECONDS = 60


class CursorRetryableError(Exception):
    pass


@dataclasses.dataclass
class CursorResumeConfig:
    # Start (epoch ms) of the window being processed when the sync was interrupted.
    # None for the non-windowed endpoints (members, spend).
    window_start: int | None = None
    # 1-based page to resume from within that window (or within the spend listing).
    page: int = 1


def _to_epoch_ms(value: Any) -> int:
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(aware.timestamp() * 1000)
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
    if isinstance(value, int | float):
        return int(value)
    return int(str(value))


def _from_epoch_ms(value: Any) -> datetime:
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


def _now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def _basic_token(api_key: str) -> str:
    # Cursor's Admin API uses HTTP Basic auth with the API key as the username and an empty password.
    return base64.b64encode(f"{api_key}:".encode("ascii")).decode("ascii")


def _redact_values(api_key: str) -> tuple[str, ...]:
    # Mask both the raw key and the derived Basic token so neither leaks into logged URLs/samples.
    return (api_key, _basic_token(api_key))


def _make_session(api_key: str) -> requests.Session:
    # Redirects are pinned off so the credential can't be replayed to a cross-host redirect target;
    # urllib3 retries are disabled so tenacity (on `_fetch`) is the single retry layer.
    return make_tracked_session(
        headers={"Authorization": f"Basic {_basic_token(api_key)}", "Accept": "application/json"},
        redact_values=_redact_values(api_key),
        allow_redirects=False,
        retry=Retry(total=0),
    )


@retry(
    retry=retry_if_exception_type(
        (
            CursorRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(6),
    # The main read endpoints are limited to ~20 requests/minute per team, so back off far enough
    # for the rate-limit window to reset before giving up.
    wait=wait_exponential_jitter(initial=3, max=70),
    reraise=True,
)
def _fetch(
    session: requests.Session,
    method: str,
    url: str,
    logger: FilteringBoundLogger,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = session.request(
        method,
        url,
        json=json_body,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise CursorRetryableError(f"Cursor API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Cursor API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> bool:
    try:
        response = _make_session(api_key).get(f"{CURSOR_BASE_URL}/teams/members", timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _usage_event_id(item: dict[str, Any]) -> str:
    """Deterministic id for a usage event, hashed from the raw payload.

    The filtered-usage-events endpoint returns no event identifier, so this synthesizes one:
    identical payloads (the same event re-fetched across overlapping incremental windows)
    collapse to one row on merge, while any field difference yields a distinct key. Two
    genuinely identical events in the same millisecond would collapse too — an accepted
    tradeoff versus unbounded duplication.
    """
    return hashlib.sha256(orjson.dumps(item, option=orjson.OPT_SORT_KEYS)).hexdigest()


def _normalize_daily_usage(item: dict[str, Any]) -> dict[str, Any]:
    if "date" in item and item["date"] is not None:
        item["date"] = _from_epoch_ms(item["date"])
    return item


def _normalize_usage_event(item: dict[str, Any]) -> dict[str, Any]:
    item["id"] = _usage_event_id(item)
    # `timestamp` arrives as an epoch-ms string; convert so the column is a real datetime.
    if "timestamp" in item and item["timestamp"] is not None:
        item["timestamp"] = _from_epoch_ms(item["timestamp"])
    return item


def _build_windows(start_ms: int, end_ms: int) -> Iterator[tuple[int, int]]:
    """Chunk [start_ms, end_ms] into inclusive windows of at most MAX_WINDOW_DAYS."""
    window_ms = int(timedelta(days=MAX_WINDOW_DAYS).total_seconds() * 1000)
    window_start = start_ms
    while window_start <= end_ms:
        window_end = min(window_start + window_ms - 1, end_ms)
        yield window_start, window_end
        window_start = window_end + 1


def _has_next_page(data: dict[str, Any], page: int, items_count: int, page_size: int) -> bool:
    """Read the has-more signal from whichever pagination shape the endpoint returns.

    filtered-usage-events and daily-usage-data nest `hasNextPage` (plus `numPages`/`totalPages`)
    under `pagination`; /teams/spend returns `totalPages` at the top level. Fall back to a
    full-page heuristic when neither is present (the API silently ignoring pagination params
    would otherwise loop forever on the same rows).
    """
    pagination = data.get("pagination")
    if isinstance(pagination, dict):
        has_next = pagination.get("hasNextPage")
        if has_next is not None:
            return bool(has_next)
        total_pages = pagination.get("numPages") or pagination.get("totalPages")
        if total_pages is not None:
            return page < int(total_pages)
    total_pages = data.get("totalPages")
    if total_pages is not None:
        return page < int(total_pages)
    return items_count >= page_size


def _get_members_rows(
    session: requests.Session,
    config: CursorEndpointConfig,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    data = _fetch(session, config.method, f"{CURSOR_BASE_URL}{config.path}", logger)
    rows = data.get(config.data_key) or []
    if rows:
        yield rows


def _get_spend_rows(
    session: requests.Session,
    config: CursorEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CursorResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume is not None else 1

    while True:
        body = {
            "page": page,
            "pageSize": config.page_size,
            # Spend amounts change while we paginate; sorting by user keeps page boundaries stable.
            "sortBy": "user",
            "sortDirection": "asc",
        }
        data = _fetch(session, config.method, f"{CURSOR_BASE_URL}{config.path}", logger, json_body=body)

        rows = data.get(config.data_key) or []
        cycle_start = data.get("subscriptionCycleStart")
        for row in rows:
            row["subscriptionCycleStart"] = cycle_start

        has_next = _has_next_page(data, page, len(rows), config.page_size)

        if rows:
            yield rows
            # Save AFTER yielding so a crash re-yields the last page rather than skipping it —
            # merge dedupes on the primary key.
            if has_next:
                resumable_source_manager.save_state(CursorResumeConfig(page=page + 1))

        if not rows or not has_next:
            break
        page += 1


def _get_windowed_rows(
    session: requests.Session,
    config: CursorEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CursorResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    end_ms = _now_ms()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.window_start is not None:
        start_ms = resume.window_start
        first_window_page = resume.page
        logger.debug(f"Cursor: resuming {config.name} from window_start={start_ms}, page={first_window_page}")
    else:
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            # startDate/endDate bounds are inclusive, so starting at the watermark re-fetches the
            # rows at exactly the watermark value — merge dedupes them, and for daily_usage it also
            # refreshes the partial day the previous sync ended on.
            start_ms = min(_to_epoch_ms(db_incremental_field_last_value), end_ms)
        else:
            start_ms = end_ms - int(timedelta(days=DEFAULT_LOOKBACK_DAYS).total_seconds() * 1000)
        first_window_page = 1

    if config.name == "usage_events":
        normalize = _normalize_usage_event
    elif config.name == "daily_usage":
        normalize = _normalize_daily_usage
    else:
        raise ValueError(f"No normalizer defined for windowed endpoint: {config.name}")

    for window_start, window_end in _build_windows(start_ms, end_ms):
        page = first_window_page
        first_window_page = 1  # only the resumed-into window starts mid-pagination

        while True:
            body = {
                "startDate": window_start,
                "endDate": window_end,
                "page": page,
                "pageSize": config.page_size,
            }
            data = _fetch(session, config.method, f"{CURSOR_BASE_URL}{config.path}", logger, json_body=body)

            items = data.get(config.data_key) or []
            rows = [normalize(item) for item in items]
            has_next = _has_next_page(data, page, len(items), config.page_size)

            if rows:
                yield rows
                # Save AFTER yielding so a crash re-yields the last batch rather than skipping it.
                if has_next:
                    resumable_source_manager.save_state(CursorResumeConfig(window_start=window_start, page=page + 1))
                else:
                    next_window = window_end + 1
                    if next_window <= end_ms:
                        resumable_source_manager.save_state(CursorResumeConfig(window_start=next_window, page=1))

            if not items or not has_next:
                break
            page += 1


def cursor_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CursorResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = CURSOR_ENDPOINTS.get(endpoint)
    if config is None:
        raise ValueError(f"Unknown Cursor endpoint: {endpoint}")

    def get_rows() -> Iterator[list[dict[str, Any]]]:
        session = _make_session(api_key)

        if endpoint == "members":
            yield from _get_members_rows(session, config, logger)
        elif endpoint == "spend":
            yield from _get_spend_rows(session, config, logger, resumable_source_manager)
        else:
            yield from _get_windowed_rows(
                session,
                config,
                logger,
                resumable_source_manager,
                should_use_incremental_field,
                db_incremental_field_last_value,
            )

    return SourceResponse(
        name=endpoint,
        items=get_rows,
        primary_keys=config.primary_keys,
        partition_keys=[config.partition_key] if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        sort_mode="asc",
    )
