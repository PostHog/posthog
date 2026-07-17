import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.uptimerobot.settings import (
    PAGE_LIMIT,
    RESPONSE_TIMES_INITIAL_LOOKBACK_DAYS,
    RESPONSE_TIMES_WINDOW_DAYS,
    UPTIMEROBOT_ENDPOINTS,
    UptimeRobotEndpointConfig,
)

UPTIMEROBOT_BASE_URL = "https://api.uptimerobot.com/v2"

# Stable prefix for credential failures — matched by `get_non_retryable_errors` on the source class.
AUTH_ERROR_PREFIX = "UptimeRobot API key was rejected"


class UptimeRobotRetryableError(Exception):
    pass


class UptimeRobotAuthError(Exception):
    pass


class UptimeRobotAPIError(Exception):
    pass


@dataclasses.dataclass
class UptimeRobotResumeConfig:
    # Next 0-indexed row offset to fetch within the current listing.
    offset: int = 0
    # response_times only: Unix start of the 7-day window being fetched. None for other endpoints.
    window_start: int | None = None


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


@retry(
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
        rows = payload.get(config.response_key) or []
        next_offset = _next_offset(payload, offset, len(rows))

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
            rows.append({**entry, "monitor_id": monitor.get("id")})
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
) -> Iterator[list[dict[str, Any]]]:
    config = UPTIMEROBOT_ENDPOINTS[endpoint]
    session = make_tracked_session()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    last_value_ts = (
        _to_unix_timestamp(db_incremental_field_last_value)
        if should_use_incremental_field and config.supports_incremental
        else None
    )

    if config.monitor_list_key == "response_times":
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
        ),
        primary_keys=config.primary_keys,
        # Fan-out endpoints aggregate rows across monitor pages (and, for response_times, time
        # windows), so batch order isn't globally ascending. "desc" defers the incremental
        # watermark to successful job end, where the max over the whole run is safe.
        sort_mode="desc" if config.monitor_list_key else "asc",
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
