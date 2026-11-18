import gzip
import json
import base64
import zipfile
import tempfile
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.sources.amplitude.settings import (
    AMPLITUDE_ENDPOINTS,
    AMPLITUDE_HOSTS,
    COMPOSITION_ENDPOINT,
    COMPOSITION_PROPERTIES,
    DASHBOARD_LOOKBACK_DAYS,
    EVENTS_DEFAULT_LOOKBACK_DAYS,
    EVENTS_EXPORT_LATENCY_HOURS,
    EVENTS_EXPORT_WINDOW_HOURS,
    RETENTION_ENDPOINT,
    RETENTION_RETURN_EVENT,
    RETENTION_START_EVENT,
    REVENUE_LTV_ENDPOINT,
    REVENUE_LTV_METRICS,
    AmplitudeEndpointConfig,
)
from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceResponse,
    frozen,
    make_tracked_session,
    retry_with_deadline,
)

REQUEST_TIMEOUT_SECONDS = 600
RETRY_MAX_ATTEMPTS = 5

# Stream export archives to disk rather than buffering the whole compressed body in memory.
# A 24h window can be gigabytes, so we spool to a temporary file that rolls over to disk once
# it exceeds this in-memory threshold, keeping worker memory bounded regardless of export size.
EXPORT_DOWNLOAD_CHUNK_BYTES = 1024 * 1024
EXPORT_SPOOL_MAX_BYTES = 32 * 1024 * 1024

# Amplitude export timestamps are UTC strings formatted as "yyyy-MM-dd HH:mm:ss.SSSSSS"
# (and occasionally without the microsecond component). We normalize them to real datetimes
# so the incremental cursor and partition columns are typed as timestamps in the warehouse.
_AMPLITUDE_TS_FIELDS = (
    "event_time",
    "server_upload_time",
    "server_received_time",
    "client_event_time",
    "client_upload_time",
    "processed_time",
)
_AMPLITUDE_TS_FORMATS = ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S")


class AmplitudeRetryableError(Exception):
    pass


# Amplitude has occasionally served a 2xx export response whose body isn't a valid zip
# archive (e.g. truncated by a network blip). Raised as retryable so Temporal retries the
# activity and re-downloads the window, rather than failing the sync outright.
AMPLITUDE_INVALID_ARCHIVE_ERROR = "Amplitude export response was not a valid zip archive"


@dataclasses.dataclass(frozen=False)
class AmplitudeResumeConfig:
    # ISO 8601 UTC timestamp marking the start of the next export window to fetch.
    window_start: str


def _host(region: str) -> str:
    return AMPLITUDE_HOSTS.get(region, AMPLITUDE_HOSTS["us"])


def _auth_headers(api_key: str, secret_key: str) -> dict[str, str]:
    token = base64.b64encode(f"{api_key}:{secret_key}".encode("ascii")).decode("ascii")
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


def _parse_amplitude_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    for fmt in _AMPLITUDE_TS_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    for ts_field in _AMPLITUDE_TS_FIELDS:
        if ts_field in event:
            parsed = _parse_amplitude_ts(event[ts_field])
            if parsed is not None:
                event[ts_field] = parsed
    return event


def _coerce_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    parsed = _parse_amplitude_ts(value)
    if parsed is not None:
        return parsed
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _floor_to_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def validate_credentials(api_key: str, secret_key: str, region: str) -> tuple[bool, Optional[str]]:
    # Probe the lightweight annotations endpoint: it returns a small JSON body, uses the same
    # API key + secret key as the Export API, and is available to every project.
    url = f"{_host(region)}/api/2/annotations"
    try:
        response = make_tracked_session().get(url, headers=_auth_headers(api_key, secret_key), timeout=30)
    except Exception as e:
        return False, f"Could not reach Amplitude ({e}). Please check your network and selected region, then retry."

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return (
            False,
            "Amplitude rejected the credentials. Check the API key and secret key (Settings → "
            "Organization settings → Projects in Amplitude) and that the selected region matches your project.",
        )
    return False, f"Unexpected response from Amplitude (status {response.status_code})."


@retry_with_deadline(
    retry=retry_if_exception_type((AmplitudeRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(RETRY_MAX_ATTEMPTS),
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _get(session: requests.Session, url: str, headers: dict[str, str], stream: bool = False) -> requests.Response:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, stream=stream)

    if response.status_code == 429 or response.status_code >= 500:
        raise AmplitudeRetryableError(f"Amplitude API error (retryable): status={response.status_code}, url={url}")

    return response


def _iter_export_window(
    session: requests.Session,
    host: str,
    headers: dict[str, str],
    start_param: str,
    end_param: str,
    logger: FilteringBoundLogger,
) -> Iterator[dict[str, Any]]:
    url = f"{host}/api/2/export?{urlencode({'start': start_param, 'end': end_param})}"
    response = _get(session, url, headers, stream=True)

    # Amplitude returns 404 (not an empty 200) when a window contains no events. That is a
    # normal outcome for sparse windows, not an error — skip the window and continue.
    if response.status_code == 404:
        logger.debug(f"Amplitude: no events for window {start_param}-{end_param}")
        return

    if not response.ok:
        logger.error(f"Amplitude export error: status={response.status_code}, body={response.text[:500]}, url={url}")
        response.raise_for_status()

    # The export response is a zip archive of gzipped JSON-lines files (one event per line).
    # Spool it to a temporary file (in memory up to EXPORT_SPOOL_MAX_BYTES, then on disk) so a
    # large 24h window never has to be held entirely in memory before rows are yielded.
    with tempfile.SpooledTemporaryFile(max_size=EXPORT_SPOOL_MAX_BYTES) as buffer:
        for chunk in response.iter_content(chunk_size=EXPORT_DOWNLOAD_CHUNK_BYTES):
            buffer.write(chunk)
        buffer.seek(0)
        try:
            archive = zipfile.ZipFile(buffer)
        except zipfile.BadZipFile as e:
            raise AmplitudeRetryableError(f"{AMPLITUDE_INVALID_ARCHIVE_ERROR}: url={url}") from e

        # A central directory can parse fine while an individual entry's payload is corrupt
        # (truncated gzip member, bad CRC) — that only surfaces once the entry is read, so it
        # needs its own retryable classification alongside the archive-open check above.
        try:
            with archive:
                for entry in archive.namelist():
                    with archive.open(entry) as raw, gzip.open(raw) as decompressed:
                        for line in decompressed:
                            if not line.strip():
                                continue
                            yield _normalize_event(json.loads(line))
        except (zipfile.BadZipFile, gzip.BadGzipFile, EOFError) as e:
            raise AmplitudeRetryableError(f"{AMPLITUDE_INVALID_ARCHIVE_ERROR}: url={url}") from e


def _get_events_rows(
    api_key: str,
    secret_key: str,
    region: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AmplitudeResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[dict[str, Any]]:
    host = _host(region)
    headers = _auth_headers(api_key, secret_key)
    session = make_tracked_session()

    end_boundary = _floor_to_hour(datetime.now(UTC) - timedelta(hours=EVENTS_EXPORT_LATENCY_HOURS))

    last_value = _coerce_datetime(db_incremental_field_last_value) if should_use_incremental_field else None
    if last_value is not None:
        start = _floor_to_hour(last_value)
    else:
        start = _floor_to_hour(end_boundary - timedelta(days=EVENTS_DEFAULT_LOOKBACK_DAYS))

    # A persisted resume cursor takes precedence so a heartbeat-timed-out activity picks up
    # at the window it was processing rather than recomputing from the incremental value.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        resumed = _coerce_datetime(resume.window_start)
        if resumed is not None:
            start = _floor_to_hour(resumed)
            logger.debug(f"Amplitude: resuming events export from {start.isoformat()}")

    cursor = start
    while cursor <= end_boundary:
        # `end` is inclusive at hour granularity, so a 24h window spans `cursor` .. `cursor + 23h`.
        window_last_hour = min(cursor + timedelta(hours=EVENTS_EXPORT_WINDOW_HOURS - 1), end_boundary)
        start_param = cursor.strftime("%Y%m%dT%H")
        end_param = window_last_hour.strftime("%Y%m%dT%H")

        yield from _iter_export_window(session, host, headers, start_param, end_param, logger)

        cursor = window_last_hour + timedelta(hours=1)
        # Save state after a window is fully yielded. On resume we re-fetch from this window
        # start; merge semantics on `uuid` dedupe any rows seen twice.
        resumable_source_manager.save_state(AmplitudeResumeConfig(window_start=cursor.isoformat()))


def _fetch_list(
    session: requests.Session,
    host: str,
    path: str,
    headers: dict[str, str],
    data_selector: str | None,
    name: str,
    logger: FilteringBoundLogger,
    params: Optional[dict[str, str]] = None,
) -> list[Any]:
    url = f"{host}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"

    response = _get(session, url, headers)
    if not response.ok:
        logger.error(f"Amplitude {name} error: status={response.status_code}, body={response.text[:500]}")
        response.raise_for_status()

    body = response.json()
    if data_selector is not None and isinstance(body, dict):
        return body.get(data_selector, [])
    if isinstance(body, list):
        return body
    return []


def _get_list_rows(
    api_key: str,
    secret_key: str,
    region: str,
    config: AmplitudeEndpointConfig,
    logger: FilteringBoundLogger,
) -> Iterator[dict[str, Any]]:
    session = make_tracked_session()
    yield from _fetch_list(
        session,
        _host(region),
        config.path,
        _auth_headers(api_key, secret_key),
        config.data_selector,
        config.name,
        logger,
    )


def _get_fanout_rows(
    api_key: str,
    secret_key: str,
    region: str,
    config: AmplitudeEndpointConfig,
    logger: FilteringBoundLogger,
) -> Iterator[dict[str, Any]]:
    fanout = config.fanout
    assert fanout is not None

    host = _host(region)
    headers = _auth_headers(api_key, secret_key)
    session = make_tracked_session()

    parents = _fetch_list(session, host, fanout.parent_path, headers, fanout.parent_data_selector, config.name, logger)

    for parent in parents:
        if not isinstance(parent, dict):
            continue
        parent_value = parent.get(fanout.join_field)
        if not isinstance(parent_value, str) or not parent_value:
            continue

        try:
            rows = _fetch_list(
                session,
                host,
                config.path,
                headers,
                config.data_selector,
                config.name,
                logger,
                params={fanout.join_field: parent_value},
            )
        except requests.HTTPError as e:
            # Amplitude answers 400 "Not found" for an event type deleted between listing the
            # parents and querying it. Skip that parent instead of failing the whole table.
            if e.response is not None and e.response.status_code == 400:
                logger.warning(
                    f"Amplitude {config.name}: skipping {fanout.join_field}={parent_value} (Amplitude returned 400)"
                )
                continue
            raise

        for row in rows:
            if not isinstance(row, dict):
                continue
            # Amplitude omits this on shared properties, so set it from the value we queried with.
            row[fanout.join_field] = parent_value
            yield row


def _parse_chart_date(label: Any, end: date) -> date:
    if not isinstance(label, str):
        raise ValueError(f"Amplitude returned an unrecognized chart date: {label!r}")
    try:
        return date.fromisoformat(label)
    except ValueError:
        pass
    # The retention chart labels its dates as "Aug 14", with no year. Every date in the window is
    # on or before `end`, and the window is shorter than a year, so the year is the latest one
    # that does not put the date after `end`.
    for year in (end.year, end.year - 1):
        try:
            parsed = datetime.strptime(f"{label} {year}", "%b %d %Y").date()
        except ValueError:
            continue
        if parsed <= end:
            return parsed
    raise ValueError(f"Amplitude returned an unrecognized chart date: {label!r}")


@frozen
class DashboardWindow:
    start: date
    end: date

    @property
    def params(self) -> dict[str, str]:
        return {"start": self.start.strftime("%Y%m%d"), "end": self.end.strftime("%Y%m%d")}


def _dashboard_window() -> DashboardWindow:
    end = datetime.now(UTC).date()
    return DashboardWindow(start=end - timedelta(days=DASHBOARD_LOOKBACK_DAYS - 1), end=end)


def _fetch_chart(
    session: requests.Session,
    host: str,
    headers: dict[str, str],
    config: AmplitudeEndpointConfig,
    logger: FilteringBoundLogger,
    params: dict[str, str],
) -> dict[str, Any]:
    url = f"{host}{config.path}?{urlencode(params)}"
    response = _get(session, url, headers)
    if not response.ok:
        logger.error(f"Amplitude {config.name} error: status={response.status_code}, body={response.text[:500]}")
        response.raise_for_status()

    body = response.json()
    data = body.get(config.data_selector) if isinstance(body, dict) and config.data_selector else None
    return data if isinstance(data, dict) else {}


def _first_series(data: dict[str, Any]) -> dict[str, Any]:
    # We send no segments, so the chart has a single series.
    series = data.get("series")
    if isinstance(series, list) and series and isinstance(series[0], dict):
        return series[0]
    return {}


def _get_retention_rows(
    api_key: str,
    secret_key: str,
    region: str,
    config: AmplitudeEndpointConfig,
    logger: FilteringBoundLogger,
) -> Iterator[dict[str, Any]]:
    window = _dashboard_window()
    data = _fetch_chart(
        make_tracked_session(),
        _host(region),
        _auth_headers(api_key, secret_key),
        config,
        logger,
        params={
            "se": json.dumps({"event_type": RETENTION_START_EVENT}),
            "re": json.dumps({"event_type": RETENTION_RETURN_EVENT}),
            "rm": "nday",
            "i": "1",
            **window.params,
        },
    )

    values = _first_series(data).get("values")
    if not isinstance(values, dict):
        return
    for label, buckets in values.items():
        if not isinstance(buckets, list):
            continue
        cohort_date = _parse_chart_date(label, window.end)
        # Index 0 holds the cohort size, and index N + 1 holds day N retention.
        for index, bucket in enumerate(buckets[1:]):
            if isinstance(bucket, dict):
                yield {**bucket, "date": cohort_date, "day": index}


def _get_composition_rows(
    api_key: str,
    secret_key: str,
    region: str,
    config: AmplitudeEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AmplitudeResumeConfig],
) -> Iterator[dict[str, Any]]:
    window = _dashboard_window()
    host = _host(region)
    headers = _auth_headers(api_key, secret_key)
    session = make_tracked_session()

    for prop in COMPOSITION_PROPERTIES:
        data = _fetch_chart(
            session,
            host,
            headers,
            config,
            logger,
            params={**window.params, "p": prop},
        )
        series = data.get("series")
        counts = series[0] if isinstance(series, list) and series and isinstance(series[0], list) else []
        x_values = data.get("xValues")
        for value, users in zip(x_values if isinstance(x_values, list) else [], counts):
            # Values of different properties share one column, so keep them all as strings.
            yield {"property": prop, "value": str(value), "users": users}
        resumable_source_manager.safe_point()


def _get_revenue_ltv_rows(
    api_key: str,
    secret_key: str,
    region: str,
    config: AmplitudeEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AmplitudeResumeConfig],
) -> Iterator[dict[str, Any]]:
    window = _dashboard_window()
    host = _host(region)
    headers = _auth_headers(api_key, secret_key)
    session = make_tracked_session()

    for metric_param, metric in REVENUE_LTV_METRICS.items():
        data = _fetch_chart(
            session,
            host,
            headers,
            config,
            logger,
            params={
                **window.params,
                "m": str(metric_param),
                "i": "1",
            },
        )
        values = _first_series(data).get("values")
        if isinstance(values, dict):
            for label, row in values.items():
                if isinstance(row, dict):
                    yield {**row, "date": _parse_chart_date(label, window.end), "metric": metric}
        resumable_source_manager.safe_point()


def _get_rows(
    api_key: str,
    secret_key: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AmplitudeResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[Any]:
    config = AMPLITUDE_ENDPOINTS[endpoint]
    if config.is_export:
        yield from _get_events_rows(
            api_key=api_key,
            secret_key=secret_key,
            region=region,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )
    elif endpoint == RETENTION_ENDPOINT:
        yield from _get_retention_rows(api_key, secret_key, region, config, logger)
    elif endpoint == COMPOSITION_ENDPOINT:
        yield from _get_composition_rows(api_key, secret_key, region, config, logger, resumable_source_manager)
    elif endpoint == REVENUE_LTV_ENDPOINT:
        yield from _get_revenue_ltv_rows(api_key, secret_key, region, config, logger, resumable_source_manager)
    elif config.fanout is not None:
        yield from _get_fanout_rows(api_key, secret_key, region, config, logger)
    else:
        yield from _get_list_rows(api_key, secret_key, region, config, logger)


def amplitude_source(
    api_key: str,
    secret_key: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AmplitudeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = AMPLITUDE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: _get_rows(
            api_key=api_key,
            secret_key=secret_key,
            region=region,
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
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
