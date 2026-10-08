import io
import re
import csv
from collections.abc import Buffer, Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.appsflyer.settings import (
    APPSFLYER_ENDPOINTS,
    AppsFlyerEndpointConfig,
    AppsFlyerReportKind,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

APPSFLYER_BASE_URL = "https://hq1.appsflyer.com"
# Aggregate pull requests cap the date range at ~1000 days.
MAX_WINDOW_DAYS = 999
# AppsFlyer doesn't finalize data until ~48h after the UTC day; re-fetch the
# trailing days each incremental run (merge dedupes on the dimension key).
LOOKBACK_DAYS = 2
# Raw-data pulls are refused beyond a 90-day historical lookback ("Raw reports historical
# lookback is limited to 90 days"), so never ask for a window that starts earlier.
RAW_MAX_LOOKBACK_DAYS = 89
# Raw reports are truncated server-side at this many rows; ask for the larger of the two
# allowed caps and warn when a window fills it, because the rest is dropped silently.
RAW_MAX_ROWS = 1_000_000
# Raw reports are pulled in chronological windows rather than one long range, so the stream is
# ascending across windows even though AppsFlyer documents no order within one. Keep the window
# wide enough that a 90-day backfill stays inside the account's daily report quota.
RAW_MAX_REQUEST_DAYS = 7
# An incremental run must be able to re-cover a whole window, because a worker shutdown can
# interrupt one mid-way and rows within it are not ordered. So never look back less than a window.
RAW_LOOKBACK_DAYS = RAW_MAX_REQUEST_DAYS
# The Master API serves at most 31 days per call, so a backfill walks it in windows.
MASTER_MAX_REQUEST_DAYS = 31
# Each window is one call against the account's daily report quota, so bound the backfill.
MASTER_MAX_LOOKBACK_DAYS = 365
# Master API KPIs are LTV measures that keep accruing after install day, so an incremental run
# re-pulls the trailing month. That also covers a whole request window, as above.
MASTER_LOOKBACK_DAYS = MASTER_MAX_REQUEST_DAYS
REQUEST_TIMEOUT_SECONDS = 300
MAX_RETRY_ATTEMPTS = 5
# Yield rows in chunks so huge reports don't build one giant list.
CHUNK_SIZE = 5000
# Pull the report CSV off the wire in 64 KiB reads.
REPORT_CHUNK_BYTES = 1 << 16


@frozen
class _ReportWindow:
    start: date
    end: date


class _ResponseByteStream(io.RawIOBase):
    """Read a streaming response body through ``iter_content`` as a binary file.

    Wrapping ``response.raw`` directly crashes once the body is read: urllib3 closes
    the raw stream as it reads the last byte, and a ``TextIOWrapper`` over the
    now-closed stream raises ``ValueError: I/O operation on closed file`` instead of
    reporting EOF. ``iter_content`` also turns a dropped connection into a retryable
    ``requests`` error mid-stream.
    """

    def __init__(self, response: requests.Response, chunk_size: int) -> None:
        self._chunks = response.iter_content(chunk_size=chunk_size)
        self._buffer = b""

    def readable(self) -> bool:
        return True

    def readinto(self, target: Buffer) -> int:
        while not self._buffer:
            try:
                self._buffer = next(self._chunks)
            except StopIteration:
                return 0
        view = memoryview(target).cast("B")
        take = min(len(view), len(self._buffer))
        view[:take] = self._buffer[:take]
        self._buffer = self._buffer[take:]
        return take


class AppsFlyerRetryableError(Exception):
    pass


class AppsFlyerCredentialsError(Exception):
    """A credential check failed for a reason we can explain to the user (bad token, bad app id)."""

    pass


def _get_session(api_token: str) -> requests.Session:
    # the v5 docs are a bit ambiguous about whether the return format defaults to CSV
    # or JSON, so we explicitly request CSV for safety.
    return make_tracked_session(
        headers={"Authorization": f"Bearer {api_token}", "Accept": "text/csv"},
        redact_values=(api_token,),
    )


def _validate_app_id(app_id: str) -> str:
    app_id = app_id.strip()
    if not re.fullmatch(r"[a-zA-Z0-9._-]+", app_id):
        raise ValueError(f"Invalid AppsFlyer app id: {app_id}")
    return app_id


def _normalize_header(header: str) -> str:
    """CSV headers like 'Media Source (pid)' become stable snake_case columns."""
    return re.sub(r"[^0-9a-zA-Z]+", "_", header).strip("_").lower()


def _to_date(value: Any) -> date:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC).date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _parse_csv_rows(
    source: str | Iterable[str], logger: FilteringBoundLogger | None = None
) -> Iterator[dict[str, Any]]:
    reader = csv.reader(io.StringIO(source) if isinstance(source, str) else source)
    headers: list[str] | None = None
    for row in reader:
        if headers is None:
            headers = [_normalize_header(header) for header in row]
            continue
        if not any(cell.strip() for cell in row):
            continue
        # zip would silently truncate a short row, leaving primary-key columns absent and
        # corrupting dedupe — drop the malformed row instead so the failure is explicit.
        if len(row) != len(headers):
            if logger is not None:
                logger.warning(
                    "AppsFlyer CSV row length mismatch; skipping row",
                    expected=len(headers),
                    got=len(row),
                )
            continue
        yield dict(zip(headers, row))


def _report_url(config: AppsFlyerEndpointConfig, app_id: str, params: dict[str, str]) -> str:
    if config.kind == AppsFlyerReportKind.MASTER:
        path = f"/api/master-agg-data/v4/app/{quote(app_id)}"
    elif config.kind == AppsFlyerReportKind.RAW:
        path = f"/api/raw-data/export/app/{quote(app_id)}/{config.report}/v5"
    else:
        path = f"/api/agg-data/export/app/{quote(app_id)}/{config.report}/v5"
    return f"{APPSFLYER_BASE_URL}{path}?{urlencode(params)}"


def _request_params(config: AppsFlyerEndpointConfig, window: _ReportWindow) -> dict[str, str]:
    params = {"from": window.start.strftime("%Y-%m-%d"), "to": window.end.strftime("%Y-%m-%d")}
    if config.kind == AppsFlyerReportKind.RAW:
        params["maximum_rows"] = str(RAW_MAX_ROWS)
    params.update(config.extra_params)
    return params


def _max_lookback_days(kind: AppsFlyerReportKind) -> int:
    if kind == AppsFlyerReportKind.RAW:
        return RAW_MAX_LOOKBACK_DAYS
    if kind == AppsFlyerReportKind.MASTER:
        return MASTER_MAX_LOOKBACK_DAYS
    return MAX_WINDOW_DAYS


def _incremental_lookback_days(kind: AppsFlyerReportKind) -> int:
    if kind == AppsFlyerReportKind.RAW:
        return RAW_LOOKBACK_DAYS
    if kind == AppsFlyerReportKind.MASTER:
        return MASTER_LOOKBACK_DAYS
    return LOOKBACK_DAYS


def _max_request_days(kind: AppsFlyerReportKind) -> int | None:
    """Days one request may span, or ``None`` when the whole range goes in a single request."""
    if kind == AppsFlyerReportKind.RAW:
        return RAW_MAX_REQUEST_DAYS
    if kind == AppsFlyerReportKind.MASTER:
        return MASTER_MAX_REQUEST_DAYS
    return None


def _window_start(
    config: AppsFlyerEndpointConfig,
    today: date,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> date:
    earliest = today - timedelta(days=_max_lookback_days(config.kind))
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        start = _to_date(db_incremental_field_last_value) - timedelta(days=_incremental_lookback_days(config.kind))
    else:
        start = earliest
    return min(max(start, earliest), today)


def _request_windows(kind: AppsFlyerReportKind, start: date, end: date) -> Iterator[_ReportWindow]:
    span = _max_request_days(kind)
    if span is None:
        yield _ReportWindow(start=start, end=end)
        return
    window_start = start
    while window_start <= end:
        window_end = min(window_start + timedelta(days=span - 1), end)
        yield _ReportWindow(start=window_start, end=window_end)
        window_start = window_end + timedelta(days=1)


@retry(
    retry=retry_if_exception_type((AppsFlyerRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=5, max=120),
    reraise=True,
)
def _open_report(session: requests.Session, url: str, logger: FilteringBoundLogger) -> requests.Response:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS, stream=True)

    if response.status_code == 429 or response.status_code >= 500:
        response.close()
        raise AppsFlyerRetryableError(f"AppsFlyer API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"AppsFlyer API error: status={response.status_code}, body={response.text[:500]}, url={url}")
        response.close()
        response.raise_for_status()

    return response


def _iter_report_rows(session: requests.Session, url: str, logger: FilteringBoundLogger) -> Iterator[dict[str, Any]]:
    response = _open_report(session, url, logger)
    try:
        # Read physical lines off the socket rather than buffering the whole body: a raw-data
        # window can hold a million event rows. Wrapping the byte stream (instead of `iter_lines`)
        # keeps the line terminators csv needs for quoted multi-line values.
        stream = io.TextIOWrapper(
            io.BufferedReader(_ResponseByteStream(response, REPORT_CHUNK_BYTES)), encoding="utf-8", newline=""
        )
        yield from _parse_csv_rows(stream, logger)
    finally:
        response.close()


def validate_credentials(api_token: str, app_id: str) -> bool:
    """Confirm the token and app id are valid with a one-day report probe.

    Returns ``True`` when the probe succeeds. Raises ``AppsFlyerCredentialsError`` with a
    user-facing message when AppsFlyer rejects the token or app id (the status code tells the
    two apart) or returns any other unexpected status, ``AppsFlyerRetryableError`` on
    rate-limit / 5xx responses, and lets transport errors propagate so the caller can tell a
    transient failure apart from a bad credential. Never returns ``False`` — a non-200 always
    raises so the failure is never silently conflated with a bad credential.
    """
    try:
        app = _validate_app_id(app_id)
    except ValueError:
        raise AppsFlyerCredentialsError(
            "The AppsFlyer app id looks invalid. Use your app's identifier from the dashboard "
            "(e.g. 'id123456789' for iOS or the package name for Android)."
        ) from None
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    response = _get_session(api_token).get(
        f"{APPSFLYER_BASE_URL}/api/agg-data/export/app/{quote(app)}/daily_report/v5"
        f"?{urlencode({'from': today, 'to': today})}",
        timeout=30,
    )
    if response.status_code == 429 or response.status_code >= 500:
        raise AppsFlyerRetryableError(f"AppsFlyer API error (retryable): status={response.status_code}")
    if response.status_code == 200:
        return True
    # 401 is an auth failure (bad token); 403/404 mean the token is fine but the app id or
    # subscription is wrong — surface which one so the user isn't left guessing.
    if response.status_code == 401:
        raise AppsFlyerCredentialsError(
            "AppsFlyer rejected the API token. Check that you pasted a valid API token (V2) from "
            "your account's Security center → AppsFlyer API tokens."
        )
    if response.status_code == 403:
        raise AppsFlyerCredentialsError(
            "AppsFlyer denied access. Check that your account's subscription includes the aggregate "
            "Pull API and that the app id is correct."
        )
    if response.status_code == 404:
        raise AppsFlyerCredentialsError("AppsFlyer couldn't find an app with that app id. Please check the app id.")
    # Any other status is unexpected (e.g. a 400 from a malformed request) — surface the real
    # code rather than blaming the token or app id, which sends users debugging the wrong thing.
    raise AppsFlyerCredentialsError(
        f"AppsFlyer returned an unexpected response (HTTP {response.status_code}) while validating credentials. "
        "If your app id and API token (V2) look correct, please try again shortly or contact support."
    )


def get_rows(
    api_token: str,
    app_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = APPSFLYER_ENDPOINTS[endpoint]
    session = _get_session(api_token)
    app = _validate_app_id(app_id)

    today = datetime.now(UTC).date()
    start = _window_start(config, today, should_use_incremental_field, db_incremental_field_last_value)

    chunk: list[dict[str, Any]] = []
    for window in _request_windows(config.kind, start, today):
        url = _report_url(config, app, _request_params(config, window))
        rows_in_window = 0
        for row in _iter_report_rows(session, url, logger):
            rows_in_window += 1
            chunk.append(row)
            if len(chunk) >= CHUNK_SIZE:
                yield chunk
                chunk = []
        if config.kind == AppsFlyerReportKind.RAW and rows_in_window >= RAW_MAX_ROWS:
            logger.warning(
                "AppsFlyer truncated the raw report at its row cap; some rows in this window were not returned",
                report=endpoint,
                window_start=window.start.isoformat(),
                window_end=window.end.isoformat(),
                row_cap=RAW_MAX_ROWS,
            )
    if chunk:
        yield chunk


def appsflyer_source(
    api_token: str,
    app_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = APPSFLYER_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            app_id=app_id,
            endpoint=endpoint,
            logger=logger,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format=config.partition_format,
        partition_keys=[config.partition_key],
        sort_mode="asc",
        # Dimension keys can collide (e.g. blank campaign values) — an expected trait of report
        # data, not something the user can fix. Don't set has_duplicate_primary_keys: that flag
        # tells validate_incremental_sync to block incremental syncing altogether. The merge's own
        # per-batch dedup (keep-last-per-key) already resolves the collision safely.
    )
