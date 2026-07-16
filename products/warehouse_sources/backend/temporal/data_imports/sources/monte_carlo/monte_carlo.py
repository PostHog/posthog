import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.monte_carlo.settings import (
    MONTE_CARLO_ENDPOINTS,
    VALIDATE_CREDENTIALS_QUERY,
    MonteCarloEndpointConfig,
)

MONTE_CARLO_GRAPHQL_URL = "https://api.getmontecarlo.com/graphql"
REQUEST_TIMEOUT_SECONDS = 60
# getAlerts requires a createdTime/updatedTime range and caps it at 2 months; we walk
# smaller windows so a single filter never risks tripping the server-side limit.
ALERT_WINDOW = timedelta(days=30)
# Alerts history is unbounded and the API requires a time range, so the first sync is
# capped to the trailing year instead of guessing at account age.
DEFAULT_LOOKBACK_DAYS = 365


class MonteCarloRetryableError(Exception):
    pass


class MonteCarloGraphQLError(Exception):
    pass


@dataclasses.dataclass
class MonteCarloResumeConfig:
    # Relay `endCursor` (or, for offset-paginated endpoints, unused) to resume pagination from.
    cursor: str | None = None
    # Row offset for offset-paginated endpoints (monitors).
    offset: int | None = None
    # In-flight alerts time window. Both bounds are pinned so a resumed cursor is replayed
    # against the exact filter it was issued for — a shifted `before` would change page
    # contents under the cursor.
    window_after: str | None = None
    window_before: str | None = None


def _get_headers(api_key_id: str, api_key_secret: str) -> dict[str, str]:
    return {
        "x-mcd-id": api_key_id,
        "x-mcd-token": api_key_secret,
        "Content-Type": "application/json",
    }


def _format_datetime(dt: datetime) -> str:
    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def _parse_incremental_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            return None
    return None


@retry(
    retry=retry_if_exception_type(
        (
            MonteCarloRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _execute_query(
    session: requests.Session,
    query: str,
    variables: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.post(
        MONTE_CARLO_GRAPHQL_URL,
        json={"query": query, "variables": variables},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    # Monte Carlo publishes no rate-limit headers; treat 429 and transient 5xx as retryable.
    if response.status_code == 429 or response.status_code >= 500:
        raise MonteCarloRetryableError(f"Monte Carlo API error (retryable): status={response.status_code}")

    if not response.ok:
        logger.error(f"Monte Carlo API error: status={response.status_code}, body={response.text[:500]}")
        response.raise_for_status()

    payload = response.json()
    errors = payload.get("errors")
    if errors:
        messages = "; ".join(str(error.get("message", error)) for error in errors)
        raise MonteCarloGraphQLError(f"Monte Carlo GraphQL error: {messages}")

    return payload.get("data") or {}


def validate_credentials(api_key_id: str, api_key_secret: str) -> bool:
    session = make_tracked_session(headers=_get_headers(api_key_id, api_key_secret))
    try:
        response = session.post(
            MONTE_CARLO_GRAPHQL_URL,
            json={"query": VALIDATE_CREDENTIALS_QUERY, "variables": {}},
            timeout=30,
        )
        if response.status_code != 200:
            return False
        return not response.json().get("errors")
    except Exception:
        return False


def _relay_pages(
    session: requests.Session,
    config: MonteCarloEndpointConfig,
    logger: FilteringBoundLogger,
    extra_variables: dict[str, Any],
    cursor: str | None,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    """Yield (rows, next_cursor) per page. next_cursor is None on the final page."""
    while True:
        variables: dict[str, Any] = {"first": config.page_size, "after": cursor, **extra_variables}
        data = _execute_query(session, config.query, variables, logger)
        connection = data.get(config.data_path) or {}
        rows = [edge["node"] for edge in connection.get("edges") or [] if edge.get("node")]
        page_info = connection.get("pageInfo") or {}
        next_cursor = page_info.get("endCursor") if page_info.get("hasNextPage") else None

        if rows:
            yield rows, next_cursor
        if not next_cursor:
            break
        cursor = next_cursor


def _get_relay_rows(
    session: requests.Session,
    config: MonteCarloEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MonteCarloResumeConfig],
    resume: MonteCarloResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    cursor = resume.cursor if resume else None
    if cursor:
        logger.debug(f"Monte Carlo: resuming {config.name} from cursor {cursor}")

    for rows, next_cursor in _relay_pages(session, config, logger, {}, cursor):
        yield rows
        # Save AFTER yielding so a crash re-yields the last page instead of skipping it —
        # merge dedupes on the primary key.
        if next_cursor:
            resumable_source_manager.save_state(MonteCarloResumeConfig(cursor=next_cursor))


def _get_offset_rows(
    session: requests.Session,
    config: MonteCarloEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MonteCarloResumeConfig],
    resume: MonteCarloResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    offset = resume.offset if resume and resume.offset else 0
    if offset:
        logger.debug(f"Monte Carlo: resuming {config.name} from offset {offset}")

    while True:
        variables = {"limit": config.page_size, "offset": offset}
        data = _execute_query(session, config.query, variables, logger)
        rows = data.get(config.data_path) or []
        if not rows:
            break

        yield rows

        if len(rows) < config.page_size:
            break
        offset += len(rows)
        resumable_source_manager.save_state(MonteCarloResumeConfig(offset=offset))


def _alert_windows(start: datetime, end: datetime) -> Iterator[tuple[datetime, datetime]]:
    window_start = start
    while window_start < end:
        window_end = min(window_start + ALERT_WINDOW, end)
        yield window_start, window_end
        window_start = window_end


def _get_alert_rows(
    session: requests.Session,
    config: MonteCarloEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MonteCarloResumeConfig],
    resume: MonteCarloResumeConfig | None,
    incremental_field: str | None,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Walk getAlerts oldest-window-first. The API requires a created/updated time range per
    query (capped at 2 months), so both the initial backfill and incremental syncs page a
    rolling window forward to now."""
    filter_field = incremental_field or config.default_incremental_field
    # getAlerts filters on createdTime or updatedTime only; anything else would silently
    # window the wrong column, so fall back to the default.
    filter_arg = "updatedTime" if filter_field == "updatedTime" else "createdTime"

    now = datetime.now(UTC)
    start = _parse_incremental_value(db_incremental_field_last_value)
    if start is None or start > now:
        start = now - timedelta(days=DEFAULT_LOOKBACK_DAYS)

    resume_cursor: str | None = None
    pinned_before: datetime | None = None
    if resume is not None and resume.window_after is not None:
        resumed_after = _parse_incremental_value(resume.window_after)
        if resumed_after is not None:
            start = resumed_after
            resume_cursor = resume.cursor
            if resume.cursor and resume.window_before is not None:
                pinned_before = _parse_incremental_value(resume.window_before)
            logger.debug(f"Monte Carlo: resuming alerts from window_after={resume.window_after}")

    windows = list(_alert_windows(start, now))
    if pinned_before is not None and windows:
        # Replay the interrupted window with its original upper bound so the saved cursor
        # stays valid, then continue from that bound.
        windows = [(windows[0][0], pinned_before), *list(_alert_windows(pinned_before, now))]

    for index, (window_after, window_before) in enumerate(windows):
        time_range = {"after": _format_datetime(window_after), "before": _format_datetime(window_before)}
        cursor = resume_cursor
        resume_cursor = None  # only the resumed-into window starts from the saved cursor

        for rows, next_cursor in _relay_pages(session, config, logger, {filter_arg: time_range}, cursor):
            yield rows
            if next_cursor:
                resumable_source_manager.save_state(
                    MonteCarloResumeConfig(
                        cursor=next_cursor,
                        window_after=time_range["after"],
                        window_before=time_range["before"],
                    )
                )

        # Bookmark the next window so a crash between windows doesn't restart the backfill.
        if index + 1 < len(windows):
            resumable_source_manager.save_state(MonteCarloResumeConfig(window_after=time_range["before"]))


def get_rows(
    api_key_id: str,
    api_key_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MonteCarloResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = MONTE_CARLO_ENDPOINTS[endpoint]
    # One session reused across every page so urllib3 keeps the connection alive.
    session = make_tracked_session(headers=_get_headers(api_key_id, api_key_secret))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if endpoint == "alerts":
        yield from _get_alert_rows(
            session,
            config,
            logger,
            resumable_source_manager,
            resume,
            incremental_field if should_use_incremental_field else None,
            db_incremental_field_last_value if should_use_incremental_field else None,
        )
    elif config.pagination == "relay":
        yield from _get_relay_rows(session, config, logger, resumable_source_manager, resume)
    elif config.pagination == "offset":
        yield from _get_offset_rows(session, config, logger, resumable_source_manager, resume)
    else:
        data = _execute_query(session, config.query, {}, logger)
        rows = data.get(config.data_path) or []
        if rows:
            yield rows


def monte_carlo_source(
    api_key_id: str,
    api_key_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MonteCarloResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = MONTE_CARLO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key_id=api_key_id,
            api_key_secret=api_key_secret,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=endpoint_config.primary_keys,
        # getAlerts documents no within-page ordering guarantee we could verify, so the
        # incremental watermark is only persisted at successful job end (desc mode) rather
        # than checkpointed per batch against an assumed ascending order.
        sort_mode="desc" if endpoint == "alerts" else "asc",
        partition_count=1 if endpoint_config.partition_key else None,
        partition_size=1 if endpoint_config.partition_key else None,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
