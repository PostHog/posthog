from collections.abc import Iterator, Sequence
from datetime import date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.cimis.settings import (
    CIMIS_BASE_URL,
    CIMIS_DATA_EPOCH,
    CIMIS_ENDPOINTS,
    CIMIS_RECORD_CAP,
    DEFAULT_DAILY_DATA_ITEMS,
    DEFAULT_HOURLY_DATA_ITEMS,
    CimisEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

REQUEST_TIMEOUT = 60
# CIMIS sits behind a WAF that rejects requests without a browser-like User-Agent.
_USER_AGENT = "PostHog-DataWarehouse/1.0 (+https://posthog.com)"
# CIMIS rejects future dates relative to California local time, so the request upper bound is computed
# in the station network's timezone rather than UTC.
_CALIFORNIA_TZ = ZoneInfo("America/Los_Angeles")


def _california_today() -> date:
    return datetime.now(_CALIFORNIA_TZ).date()


class CimisRetryableError(Exception):
    pass


class CimisHTTPError(Exception):
    """Sanitized HTTP error for non-2xx CIMIS responses.

    requests' own ``raise_for_status()`` embeds the full request URL — which carries the appKey in
    its query string — in the exception message, so it must not be used here. This error reports only
    the status code, keeping the credential out of logs, error tracking, and the non-retryable matcher.
    """

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"CIMIS API error: status={status_code}")


def _headers() -> dict[str, str]:
    return {"Accept": "application/json", "User-Agent": _USER_AGENT}


def _records_per_day(scope: Optional[str]) -> int:
    return 24 if scope == "hourly" else 1


def _default_data_items(scope: Optional[str]) -> list[str]:
    return DEFAULT_HOURLY_DATA_ITEMS if scope == "hourly" else DEFAULT_DAILY_DATA_ITEMS


def parse_targets(targets: str | None) -> list[str]:
    if not targets:
        return []
    return [t.strip() for t in targets.split(",") if t.strip()]


def _chunk(items: Sequence[str], size: int) -> Iterator[list[str]]:
    for i in range(0, len(items), max(1, size)):
        yield list(items[i : i + size])


def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None


def _date_windows(start: date, end: date, window_days: int) -> Iterator[tuple[date, date]]:
    """Yield inclusive [win_start, win_end] date windows from start to end, oldest first."""
    cursor = start
    step = max(1, window_days)
    while cursor <= end:
        win_end = min(cursor + timedelta(days=step - 1), end)
        yield cursor, win_end
        cursor = win_end + timedelta(days=1)


def _flatten_record(record: dict[str, Any]) -> dict[str, Any]:
    """Flatten CIMIS measurement objects ({Value, Qc, Unit}) into scalar columns.

    Each /api/data record carries scalar identity fields (Date, Hour, Station, ...) plus one nested
    object per requested measurement, e.g. ``"DayAirTmpAvg": {"Value": "12.3", "Qc": " ", "Unit": "(F)"}``.
    Nested measurement objects become ``DayAirTmpAvg_Value`` / ``_Qc`` / ``_Unit`` columns so the table
    stays flat; everything else is passed through untouched.
    """
    flat: dict[str, Any] = {}
    for key, value in record.items():
        if isinstance(value, dict) and ("Value" in value or "Qc" in value or "Unit" in value):
            for sub_key, sub_value in value.items():
                flat[f"{key}_{sub_key}"] = sub_value
        else:
            flat[key] = value
    return flat


@retry(
    retry=retry_if_exception_type((CimisRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict[str, Any]:
    response = session.get(url, timeout=REQUEST_TIMEOUT)

    if response.status_code == 429 or response.status_code >= 500:
        raise CimisRetryableError(f"CIMIS API error (retryable): status={response.status_code}")

    if not response.ok:
        logger.error(f"CIMIS API error: status={response.status_code}, body={response.text[:500]}")
        raise CimisHTTPError(response.status_code)

    return response.json()


def _build_metadata_url(config: CimisEndpointConfig, app_key: str) -> str:
    # The metadata endpoints (station / stationzipcode / spatialzipcode) ignore appKey today, but we
    # send it so behavior stays correct if CIMIS starts enforcing it on these paths.
    return f"{CIMIS_BASE_URL}{config.path}?{urlencode({'appKey': app_key})}"


def _build_data_url(
    app_key: str,
    targets: list[str],
    unit_of_measure: str,
    data_items: list[str],
    start: date,
    end: date,
) -> str:
    params = {
        "appKey": app_key,
        "targets": ",".join(targets),
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "unitOfMeasure": unit_of_measure,
        "dataItems": ",".join(data_items),
    }
    return f"{CIMIS_BASE_URL}/data?{urlencode(params)}"


def _iter_data_records(data: dict[str, Any]) -> Iterator[dict[str, Any]]:
    providers = data.get("Data", {}).get("Providers", [])
    for provider in providers:
        for record in provider.get("Records", []):
            yield _flatten_record(record)


def _get_metadata_rows(
    config: CimisEndpointConfig, app_key: str, logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    session = make_tracked_session(headers=_headers(), redact_values=(app_key,))
    url = _build_metadata_url(config, app_key)
    data = _fetch(session, url, logger)
    rows = data.get(config.response_key, [])
    if rows:
        yield rows


def _get_data_rows(
    config: CimisEndpointConfig,
    app_key: str,
    targets: list[str],
    unit_of_measure: str,
    data_items: list[str],
    start: date,
    end: date,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    if not targets:
        raise ValueError(
            "CIMIS weather data tables require at least one target station. Set the 'Targets' field "
            "on the source to a comma-separated list of CIMIS station numbers."
        )

    session = make_tracked_session(headers=_headers(), redact_values=(app_key,))
    rpd = _records_per_day(config.scope)

    # Keep the date window as the outer loop so rows are emitted in ascending Date order even when the
    # target set is large enough to require multiple requests per window (sort_mode="asc" relies on it).
    if len(targets) * rpd <= CIMIS_RECORD_CAP:
        window_days = max(1, CIMIS_RECORD_CAP // (len(targets) * rpd))
        target_batches = [targets]
    else:
        window_days = 1
        target_batches = list(_chunk(targets, max(1, CIMIS_RECORD_CAP // rpd)))

    for win_start, win_end in _date_windows(start, end, window_days):
        for batch in target_batches:
            url = _build_data_url(app_key, batch, unit_of_measure, data_items, win_start, win_end)
            data = _fetch(session, url, logger)
            rows = list(_iter_data_records(data))
            if rows:
                yield rows


def get_rows(
    endpoint: str,
    app_key: str,
    targets: list[str],
    unit_of_measure: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = CIMIS_ENDPOINTS[endpoint]

    if not config.is_data_endpoint:
        yield from _get_metadata_rows(config, app_key, logger)
        return

    # CIMIS has no future data and rejects future dates; the upper bound is always today in California.
    end = _california_today()

    start = date.fromisoformat(CIMIS_DATA_EPOCH)
    if should_use_incremental_field:
        last_value = _to_date(db_incremental_field_last_value)
        if last_value is not None:
            # Re-fetch from the last seen day (inclusive); merge dedupes on the primary key.
            start = last_value

    if start > end:
        return

    yield from _get_data_rows(
        config, app_key, targets, unit_of_measure, _default_data_items(config.scope), start, end, logger
    )


def validate_credentials(app_key: str, targets: list[str], logger: FilteringBoundLogger) -> tuple[bool, str | None]:
    """Probe /api/data with a tiny recent window to confirm the appKey is genuine.

    The metadata endpoints don't enforce the appKey, so the only key-gated probe is /api/data. We use
    a known-good public station (2 = FivePoints) when the user hasn't supplied targets yet so source
    creation isn't gated on the targets field.

    Note: this endpoint could not be exercised end-to-end during development (the live API is fronted
    by a WAF that rejected automated probes from the build environment), so the status mapping below
    follows the documented CIMIS error contract rather than observed responses.
    """
    probe_target = targets[0] if targets else "2"
    end = _california_today()
    start = end - timedelta(days=2)
    url = _build_data_url(app_key, [probe_target], "E", ["day-air-tmp-avg"], start, end)

    try:
        session = make_tracked_session(headers=_headers(), redact_values=(app_key,))
        response = session.get(url, timeout=REQUEST_TIMEOUT)
    except Exception as exc:
        # Log only the exception type — requests exceptions embed the request URL, which carries the appKey.
        logger.warning(f"CIMIS credential validation failed to reach the API: {type(exc).__name__}")
        return False, "Could not reach the CIMIS API. Please try again."

    if response.status_code == 200:
        return True, None

    if response.status_code in (401, 403):
        return False, "Your CIMIS appKey is invalid or has not been activated. Check the key and try again."

    return False, f"CIMIS API returned status {response.status_code}."


def cimis_source(
    endpoint: str,
    app_key: str,
    targets: list[str],
    unit_of_measure: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CIMIS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            endpoint=endpoint,
            app_key=app_key,
            targets=targets,
            unit_of_measure=unit_of_measure,
            logger=logger,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
