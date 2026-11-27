import json
import time
import hashlib
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import parse_qs, quote, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceResponse,
    frozen,
    make_tracked_session,
    retry_with_deadline,
)
from products.warehouse_sources.sources.uptimerobot.settings import (
    DAILY_UPTIME_INITIAL_LOOKBACK_DAYS,
    PAGE_LIMIT,
    RESPONSE_TIMES_INITIAL_LOOKBACK_DAYS,
    RESPONSE_TIMES_WINDOW_DAYS,
    UPTIMEROBOT_ENDPOINTS,
    V3_PAGE_LIMIT,
    UptimeRobotEndpointConfig,
)

UPTIMEROBOT_BASE_URL = "https://api.uptimerobot.com/v2"
UPTIMEROBOT_V3_BASE_URL = "https://api.uptimerobot.com/v3"

# Cap on a server-requested v3 wait. Rate limits are per minute, so one window always fits.
MAX_RETRY_AFTER_SECONDS = 60

# Stable prefix for credential failures — matched by `get_non_retryable_errors` on the source class.
AUTH_ERROR_PREFIX = "UptimeRobot API key was rejected"

# getMonitors echoes back the monitor's configuration, including the HTTP Basic Auth credentials
# used to reach the monitored endpoint (`http_username`/`http_password`) and any custom request
# headers, which routinely carry bearer tokens or API keys. None of these have analytical value and
# all would let a project member with warehouse read access recover live credentials, so they're
# stripped from every row defensively regardless of endpoint.
_SENSITIVE_FIELDS: frozenset[str] = frozenset({"http_username", "http_password", "custom_http_headers"})

# Alert-contact channel types whose `value` is a plain destination (phone number, email address, or
# handle) rather than a secret. Every other type — webhook (5), Slack (11), Zapier (7), Pushover
# (9), and the growing list of integration channels — puts a URL or token in `value` that a project
# member with warehouse read access could use to forge notifications, so we redact it. Keyed on the
# numeric `type`; unknown or missing types fail closed (redacted).
_ALERT_CONTACT_PLAINTEXT_VALUE_TYPES: frozenset[int] = frozenset({1, 2, 3})

# v3 names the channel of a sent alert as a string. Only these carry a plain destination (an email
# address or a phone number); any other channel, known or not, has its recipient value redacted.
_PLAINTEXT_RECIPIENT_CHANNELS: frozenset[str] = frozenset({"email", "sms", "prosms", "voice"})


def _scrub_sensitive(row: dict[str, Any]) -> dict[str, Any]:
    if _SENSITIVE_FIELDS.isdisjoint(row):
        return row
    return {key: value for key, value in row.items() if key not in _SENSITIVE_FIELDS}


def _scrub_alert_contact(row: dict[str, Any]) -> dict[str, Any]:
    """Redact the `value` of credential-bearing alert contacts (webhook/integration channels)."""
    if "value" not in row:
        return row
    try:
        contact_type = int(row["type"])
    except (KeyError, TypeError, ValueError):
        contact_type = -1
    if contact_type in _ALERT_CONTACT_PLAINTEXT_VALUE_TYPES:
        return row
    return {**row, "value": None}


def _redact_recipient(row: dict[str, Any], value_field: str, channel_field: str) -> dict[str, Any]:
    if row.get(value_field) is None:
        return row
    channel = str(row.get(channel_field) or "").strip().lower()
    if channel in _PLAINTEXT_RECIPIENT_CHANNELS:
        return row
    return {**row, value_field: None}


def _derive_row_id(parent_id: Any, row: dict[str, Any], fields: tuple[str, ...]) -> str:
    material = json.dumps([parent_id, *(row.get(name) for name in fields)], default=str)
    return hashlib.sha256(material.encode()).hexdigest()


class UptimeRobotRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class UptimeRobotAuthError(Exception):
    pass


class UptimeRobotAPIError(Exception):
    pass


@frozen
class UptimeRobotResumeConfig:
    # Next 0-indexed row offset to fetch within the current listing.
    offset: int = 0
    # response_times only: Unix start of the 7-day window being fetched. None for other endpoints.
    window_start: int | None = None
    # v3 endpoints only: cursor of the next page to fetch.
    cursor: str | None = None
    # Fan-out endpoints only: the parent page being read (None for the first page), the index of the
    # next parent on it, and where that parent's children continue (a cursor, or a day for daily windows).
    parent_cursor: str | None = None
    parent_index: int = 0
    child_cursor: str | None = None


def _to_unix_timestamp(value: Any) -> int | None:
    """Coerce an incremental cursor (int epoch, datetime, date, or numeric string) to Unix seconds."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(aware.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(float(stripped))
        except ValueError:
            try:
                return int(datetime.fromisoformat(stripped.replace("Z", "+00:00")).timestamp())
            except ValueError:
                return None
    return None


@retry_with_deadline(
    retry=retry_if_exception_type((UptimeRobotRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _post(session: requests.Session, method: str, data: dict[str, Any], logger: FilteringBoundLogger) -> dict[str, Any]:
    """Call a v2 API method. Every v2 endpoint is a form-encoded POST with the api_key in the body.

    UptimeRobot returns HTTP 200 even for failures and signals errors in-body via
    ``{"stat": "fail", "error": {...}}``, so both layers are checked here.
    """
    url = f"{UPTIMEROBOT_BASE_URL}/{method}"
    response = session.post(url, data=data, timeout=60)

    # Rate limits are plan-based (free: 10 req/min); 429 carries a Retry-After header. Back off and
    # retry rather than failing the sync. Transient 5xx are retryable too.
    if response.status_code == 429 or response.status_code >= 500:
        raise UptimeRobotRetryableError(
            f"UptimeRobot API error (retryable): status={response.status_code}, method={method}"
        )

    if not response.ok:
        logger.error(f"UptimeRobot API error: status={response.status_code}, body={response.text}, method={method}")
        response.raise_for_status()

    payload = response.json()
    if payload.get("stat") != "ok":
        error = payload.get("error") or {}
        message = error.get("message") or str(error)
        # Invalid/missing keys surface as {"type": "invalid_parameter", "parameter_name": "api_key"}
        # (verified against the live API); monitor-scoped keys hitting non-monitor endpoints report
        # api_key errors too.
        if "api_key" in str(error.get("parameter_name") or "") or "api_key" in str(message):
            raise UptimeRobotAuthError(f"{AUTH_ERROR_PREFIX}: {message}")
        raise UptimeRobotAPIError(f"UptimeRobot API error ({error.get('type')}): {message}")

    return payload


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a delta-seconds `Retry-After` header. Anything else falls back to exponential backoff."""
    if not value:
        return None
    try:
        delay = float(value.strip())
    except ValueError:
        return None
    return delay if delay >= 0 else None


_v3_backoff = wait_exponential_jitter(initial=1, max=30)


def _v3_server_delay(retry_state: RetryCallState) -> float | None:
    exc = retry_state.outcome.exception() if retry_state.outcome is not None else None
    return exc.retry_after if isinstance(exc, UptimeRobotRetryableError) else None


def _wait_v3(retry_state: RetryCallState) -> float:
    retry_after = _v3_server_delay(retry_state)
    if retry_after is not None:
        return min(retry_after, MAX_RETRY_AFTER_SECONDS)
    return _v3_backoff(retry_state)


@retry_with_deadline(
    retry=retry_if_exception_type((UptimeRobotRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=_wait_v3,
    requested_wait=_v3_server_delay,
    reraise=True,
)
def _get_v3(
    session: requests.Session, path: str, params: dict[str, Any], logger: FilteringBoundLogger
) -> dict[str, Any]:
    """Call a v3 REST endpoint. v3 signals errors with real HTTP statuses, unlike v2."""
    response = session.get(f"{UPTIMEROBOT_V3_BASE_URL}{path}", params=params, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        retry_after = _parse_retry_after(response.headers.get("Retry-After")) if response.status_code == 429 else None
        raise UptimeRobotRetryableError(
            f"UptimeRobot API error (retryable): status={response.status_code}, method={path}",
            retry_after=retry_after,
        )

    if response.status_code == 401:
        raise UptimeRobotAuthError(f"{AUTH_ERROR_PREFIX}: status=401, method={path}")

    if not response.ok:
        logger.error(f"UptimeRobot API error: status={response.status_code}, body={response.text}, method={path}")
        response.raise_for_status()

    return response.json()


def _v3_next_cursor(payload: dict[str, Any]) -> str | None:
    """Return the cursor of the next v3 page, or None on the last page.

    /tags returns `nextCursorId`; the other list endpoints return a `nextLink` URL. Only the cursor is
    read from `nextLink`, so the bearer token is never sent to a host taken from a response body.
    """
    next_cursor_id = payload.get("nextCursorId")
    if next_cursor_id is not None:
        return str(next_cursor_id)

    next_link = payload.get("nextLink")
    if not next_link:
        return None
    cursors = parse_qs(urlparse(str(next_link)).query).get("cursor")
    return cursors[0] if cursors else None


def _get_v3_rows(
    api_key: str,
    config: UptimeRobotEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UptimeRobotResumeConfig],
    resume: UptimeRobotResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    # _get_v3 owns the retries, so the adapter retries are off to keep them from compounding.
    session = make_tracked_session(
        headers={"Authorization": f"Bearer {api_key}"}, redact_values=(api_key,), retry=Retry(total=0)
    )

    cursor = resume.cursor if resume is not None else None
    if cursor:
        logger.debug(f"UptimeRobot: resuming {config.name} from cursor {cursor}")

    while True:
        params: dict[str, Any] = {"limit": V3_PAGE_LIMIT} if config.v3_accepts_limit else {}
        if cursor:
            params["cursor"] = cursor
        payload = _get_v3(session, config.method, params, logger)
        rows = payload.get(config.response_key) or []
        next_cursor = _v3_next_cursor(payload)
        # A cursor that does not move would fetch the same page forever.
        if next_cursor == cursor:
            next_cursor = None

        if next_cursor is not None:
            resumable_source_manager.save_state(UptimeRobotResumeConfig(cursor=next_cursor))
        if rows:
            yield rows
        if next_cursor is None:
            break
        if not rows:
            resumable_source_manager.safe_point()
        cursor = next_cursor


def _parent_needs_visit(config: UptimeRobotEndpointConfig, parent: dict[str, Any], last_value_ts: int | None) -> bool:
    """An incident resolved before the watermark can get no new alerts or status updates."""
    if config.fan_out is None or not config.fan_out.skip_resolved_parents or last_value_ts is None:
        return True
    resolved_ts = _to_unix_timestamp(parent.get("resolvedAt"))
    return resolved_ts is None or resolved_ts >= last_value_ts


def _child_list_pages(
    session: requests.Session,
    config: UptimeRobotEndpointConfig,
    path: str,
    start_cursor: str | None,
    logger: FilteringBoundLogger,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    cursor = start_cursor
    while True:
        params: dict[str, Any] = {"limit": V3_PAGE_LIMIT} if config.v3_accepts_limit else {}
        if cursor:
            params["cursor"] = cursor
        payload = _get_v3(session, path, params, logger)
        next_cursor = _v3_next_cursor(payload)
        if next_cursor == cursor:
            next_cursor = None
        yield payload.get(config.response_key) or [], next_cursor
        if next_cursor is None:
            return
        cursor = next_cursor


def _daily_window_pages(
    session: requests.Session,
    path: str,
    first_day: date,
    end_day: date,
    logger: FilteringBoundLogger,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    """One request per finished UTC day in [first_day, end_day), as one row each."""
    day = first_day
    while day < end_day:
        next_day = day + timedelta(days=1)
        params = {"from": f"{day.isoformat()}T00:00:00Z", "to": f"{next_day.isoformat()}T00:00:00Z"}
        payload = _get_v3(session, path, params, logger)
        yield [{**payload, "date": day.isoformat()}], next_day.isoformat() if next_day < end_day else None
        day = next_day


def _shape_child_row(config: UptimeRobotEndpointConfig, parent_id: Any, row: dict[str, Any]) -> dict[str, Any]:
    assert config.fan_out is not None
    shaped = {**row, config.fan_out.parent_key: parent_id}
    if config.row_id_fields:
        # Derived before redaction, so two webhooks with the same name still get different ids.
        shaped["id"] = _derive_row_id(parent_id, row, config.row_id_fields)
    if config.recipient_fields is not None:
        shaped = _redact_recipient(shaped, *config.recipient_fields)
    return shaped


def _get_v3_fan_out_rows(
    api_key: str,
    config: UptimeRobotEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UptimeRobotResumeConfig],
    resume: UptimeRobotResumeConfig | None,
    last_value_ts: int | None,
    incremental_field: str | None,
) -> Iterator[list[dict[str, Any]]]:
    fan_out = config.fan_out
    assert fan_out is not None
    session = make_tracked_session(
        headers={"Authorization": f"Bearer {api_key}"}, redact_values=(api_key,), retry=Retry(total=0)
    )

    today = datetime.now(UTC).date()
    if last_value_ts is not None:
        first_day = datetime.fromtimestamp(last_value_ts, UTC).date() + timedelta(days=1)
    else:
        first_day = today - timedelta(days=DAILY_UPTIME_INITIAL_LOOKBACK_DAYS)

    page_cursor = resume.parent_cursor if resume is not None else None
    skip = resume.parent_index if resume is not None else 0
    child_cursor = resume.child_cursor if resume is not None else None
    if resume is not None:
        logger.debug(f"UptimeRobot: resuming {config.name} at parent {skip} of page {page_cursor}")

    while True:
        resumable_source_manager.save_state(
            UptimeRobotResumeConfig(parent_cursor=page_cursor, parent_index=skip, child_cursor=child_cursor)
        )
        resumable_source_manager.safe_point()
        params: dict[str, Any] = {"limit": V3_PAGE_LIMIT}
        if page_cursor:
            params["cursor"] = page_cursor
        payload = _get_v3(session, fan_out.parent_path, params, logger)
        parents = payload.get("data") or []
        next_page_cursor = _v3_next_cursor(payload)
        if next_page_cursor == page_cursor:
            next_page_cursor = None

        for index in range(skip, len(parents)):
            parent = parents[index]
            parent_id = parent.get("id")
            resume_child_cursor, child_cursor = child_cursor, None
            if parent_id is None or not _parent_needs_visit(config, parent, last_value_ts):
                continue

            path = config.method.replace("{id}", quote(str(parent_id), safe=""))
            if fan_out.daily_windows:
                start_day = date.fromisoformat(resume_child_cursor) if resume_child_cursor else first_day
                pages = _daily_window_pages(session, path, start_day, today, logger)
            else:
                pages = _child_list_pages(session, config, path, resume_child_cursor, logger)

            for rows, next_child_cursor in pages:
                if next_child_cursor is None:
                    state = UptimeRobotResumeConfig(parent_cursor=page_cursor, parent_index=index + 1)
                else:
                    state = UptimeRobotResumeConfig(
                        parent_cursor=page_cursor, parent_index=index, child_cursor=next_child_cursor
                    )
                resumable_source_manager.save_state(state)

                shaped = [_shape_child_row(config, parent_id, row) for row in rows]
                if last_value_ts is not None and incremental_field and not fan_out.daily_windows:
                    shaped = [
                        row
                        for row in shaped
                        if (row_ts := _to_unix_timestamp(row.get(incremental_field))) is None or row_ts > last_value_ts
                    ]
                if shaped:
                    yield shaped
                else:
                    resumable_source_manager.safe_point()

        if next_page_cursor is None:
            break
        page_cursor = next_page_cursor
        skip = 0


def _form_data(api_key: str, config: UptimeRobotEndpointConfig, offset: int) -> dict[str, Any]:
    return {
        "api_key": api_key,
        "format": "json",
        "offset": offset,
        "limit": PAGE_LIMIT,
        **config.extra_params,
    }


def _next_offset(payload: dict[str, Any], requested_offset: int, page_len: int) -> int | None:
    """Compute the next page offset, or None when the listing is exhausted.

    Most endpoints nest {offset, limit, total} under "pagination"; getAlertContacts returns them at
    the top level, and the docs show them as strings there — coerce defensively.
    """
    pagination = payload.get("pagination")
    if not isinstance(pagination, dict):
        pagination = payload
    try:
        offset = int(pagination.get("offset", requested_offset))
        limit = int(pagination.get("limit", PAGE_LIMIT))
        total = int(pagination["total"])
    except (KeyError, TypeError, ValueError):
        # No usable pagination metadata — assume more pages only if this one came back full.
        return requested_offset + page_len if page_len >= PAGE_LIMIT else None

    next_offset = offset + limit
    return next_offset if next_offset < total else None


def _get_top_level_rows(
    session: requests.Session,
    api_key: str,
    config: UptimeRobotEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UptimeRobotResumeConfig],
    resume: UptimeRobotResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    offset = resume.offset if resume is not None else 0
    if offset:
        logger.debug(f"UptimeRobot: resuming {config.name} from offset {offset}")

    while True:
        payload = _post(session, config.method, _form_data(api_key, config, offset), logger)
        raw_rows = payload.get(config.response_key) or []
        next_offset = _next_offset(payload, offset, len(raw_rows))

        rows = [_scrub_sensitive(row) for row in raw_rows]
        if config.redact_alert_contact_values:
            rows = [_scrub_alert_contact(row) for row in rows]
        if rows:
            yield rows
        if next_offset is None:
            break
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it — merge
        # dedupes on the primary key.
        resumable_source_manager.save_state(UptimeRobotResumeConfig(offset=next_offset))
        offset = next_offset


def _flatten_monitor_rows(
    monitors: list[dict[str, Any]], list_key: str, min_exclusive_ts: int | None
) -> list[dict[str, Any]]:
    """Flatten each monitor's nested list ("logs" / "response_times") into rows keyed by monitor_id."""
    rows: list[dict[str, Any]] = []
    for monitor in monitors:
        for entry in monitor.get(list_key) or []:
            if min_exclusive_ts is not None:
                entry_ts = _to_unix_timestamp(entry.get("datetime"))
                if entry_ts is not None and entry_ts <= min_exclusive_ts:
                    continue
            rows.append(_scrub_sensitive({**entry, "monitor_id": monitor.get("id")}))
    return rows


def _get_monitor_log_rows(
    session: requests.Session,
    api_key: str,
    config: UptimeRobotEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UptimeRobotResumeConfig],
    resume: UptimeRobotResumeConfig | None,
    last_value_ts: int | None,
) -> Iterator[list[dict[str, Any]]]:
    offset = resume.offset if resume is not None else 0
    if offset:
        logger.debug(f"UptimeRobot: resuming {config.name} from offset {offset}")

    extra: dict[str, Any] = {}
    if last_value_ts is not None:
        # logs_start_date/logs_end_date are documented as paid-plan-only; free plans return every
        # retained log regardless, so the client-side filter in _flatten_monitor_rows keeps those
        # syncs correct. Retention is bounded (~2 months on free), so the fallback stays cheap.
        extra["logs_start_date"] = last_value_ts
        extra["logs_end_date"] = int(time.time())

    while True:
        payload = _post(session, config.method, {**_form_data(api_key, config, offset), **extra}, logger)
        monitors = payload.get(config.response_key) or []
        next_offset = _next_offset(payload, offset, len(monitors))

        rows = _flatten_monitor_rows(monitors, "logs", last_value_ts)
        if rows:
            yield rows
        if next_offset is None:
            break
        resumable_source_manager.save_state(UptimeRobotResumeConfig(offset=next_offset))
        offset = next_offset


def _get_response_time_rows(
    session: requests.Session,
    api_key: str,
    config: UptimeRobotEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UptimeRobotResumeConfig],
    resume: UptimeRobotResumeConfig | None,
    last_value_ts: int | None,
) -> Iterator[list[dict[str, Any]]]:
    """Walk response-time history in 7-day windows (the API's max range per request), paginating
    monitors within each window. Window boundaries overlap by one second's worth of samples at most;
    merge dedupes on [monitor_id, datetime]."""
    now_ts = int(time.time())
    window_seconds = RESPONSE_TIMES_WINDOW_DAYS * 86400

    start_ts = last_value_ts if last_value_ts is not None else now_ts - RESPONSE_TIMES_INITIAL_LOOKBACK_DAYS * 86400

    window_start = start_ts
    offset = 0
    if resume is not None and resume.window_start is not None:
        window_start = resume.window_start
        offset = resume.offset
        logger.debug(f"UptimeRobot: resuming {config.name} from window_start={window_start}, offset={offset}")

    while window_start < now_ts:
        window_end = min(window_start + window_seconds, now_ts)
        extra = {"response_times_start_date": window_start, "response_times_end_date": window_end}

        while True:
            payload = _post(session, config.method, {**_form_data(api_key, config, offset), **extra}, logger)
            monitors = payload.get(config.response_key) or []
            next_offset = _next_offset(payload, offset, len(monitors))

            rows = _flatten_monitor_rows(monitors, "response_times", last_value_ts)
            if rows:
                yield rows
            if next_offset is None:
                break
            resumable_source_manager.save_state(UptimeRobotResumeConfig(offset=next_offset, window_start=window_start))
            offset = next_offset

        window_start = window_end
        offset = 0
        if window_start < now_ts:
            resumable_source_manager.save_state(UptimeRobotResumeConfig(offset=0, window_start=window_start))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UptimeRobotResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = UPTIMEROBOT_ENDPOINTS[endpoint]
    session = make_tracked_session()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    last_value_ts = (
        _to_unix_timestamp(db_incremental_field_last_value)
        if should_use_incremental_field and config.supports_incremental
        else None
    )

    if config.fan_out is not None:
        yield from _get_v3_fan_out_rows(
            api_key,
            config,
            logger,
            resumable_source_manager,
            resume,
            last_value_ts,
            incremental_field or (config.incremental_fields[0]["field"] if config.incremental_fields else None),
        )
    elif config.api_version == "v3":
        yield from _get_v3_rows(api_key, config, logger, resumable_source_manager, resume)
    elif config.monitor_list_key == "response_times":
        yield from _get_response_time_rows(
            session, api_key, config, logger, resumable_source_manager, resume, last_value_ts
        )
    elif config.monitor_list_key == "logs":
        yield from _get_monitor_log_rows(
            session, api_key, config, logger, resumable_source_manager, resume, last_value_ts
        )
    else:
        yield from _get_top_level_rows(session, api_key, config, logger, resumable_source_manager, resume)


def uptimerobot_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UptimeRobotResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = UPTIMEROBOT_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        # Fan-out endpoints aggregate rows across monitor pages (and, for response_times, time
        # windows), so batch order isn't globally ascending. "desc" defers the incremental
        # watermark to successful job end, where the max over the whole run is safe. v3 fan-out
        # endpoints read one series per parent, so their order is not known.
        sort_mode=None if config.fan_out else "desc" if config.monitor_list_key else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format=config.partition_format if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Probe getMonitors with limit=1 to confirm the key is genuine.

    getMonitors is the one endpoint every key type (main, read-only, monitor-specific) can call, so
    a passing probe never blocks a legitimately scoped key. Returns ``(ok, error_message)``.
    """
    try:
        response = make_tracked_session().post(
            f"{UPTIMEROBOT_BASE_URL}/getMonitors",
            data={"api_key": api_key, "format": "json", "limit": 1},
            timeout=10,
        )
    except Exception:
        return False, "Could not connect to UptimeRobot"

    if response.status_code != 200:
        return False, f"UptimeRobot returned an unexpected status code ({response.status_code})"

    try:
        payload = response.json()
    except ValueError:
        return False, "UptimeRobot returned an unexpected response"

    if payload.get("stat") == "ok":
        return True, None

    error = payload.get("error") or {}
    if "api_key" in str(error.get("parameter_name") or "") or "api_key" in str(error.get("message") or ""):
        return False, "Invalid UptimeRobot API key"
    return False, error.get("message") or "Could not validate UptimeRobot credentials"
