from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.sources.google_admob.settings import (
    ADMOB_HOST,
    ADMOB_LISTS,
    ADMOB_MAX_REPORT_ROWS,
    ADMOB_REPORTS,
    DATE_FIELD,
    DEFAULT_LOOKBACK_DAYS,
    LIST_PAGE_SIZE,
    MIN_START_DATE,
    REPORT_ROW_BUDGET,
    REPORT_WINDOW_DAYS,
    SPLIT_DIMENSIONS,
    SPLIT_VALUE_METRICS,
    YIELD_CHUNK_ROWS,
    AdMobListConfig,
    AdMobReportConfig,
)
from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceResponse,
    flatten_nested,
    frozen,
    make_tracked_session,
    raise_for_retryable_status,
    raise_for_status_redacted,
    resolve_incremental_start,
    vendor_retry,
)

# (connect, read). The read timeout stays well under the 300 s retry budget, so a slow report can
# time out, and the sync can ask for a smaller window, before the budget runs out.
REQUEST_TIMEOUT_SECONDS = (30, 120)
DEFAULT_API_VERSION = "v1"

# Earnings metrics come back in micros. The row keeps the exact micros value and the amount in units.
MICROS_METRICS = frozenset({"ESTIMATED_EARNINGS", "IMPRESSION_RPM", "OBSERVED_ECPM"})
INTEGER_METRICS = frozenset({"AD_REQUESTS", "CLICKS", "IMPRESSIONS", "MATCHED_REQUESTS"})

# Dimensions whose value is an ID that AdMob also labels with a readable name.
LABELLED_DIMENSIONS = frozenset({"APP", "AD_UNIT", "AD_SOURCE", "MEDIATION_GROUP"})

# Called to mint a fresh access token when the current one is rejected mid-sync.
AccessTokenRefresher = Callable[[], str]


@frozen
class AdMobResumeConfig:
    # ISO date (YYYY-MM-DD) of the first day the next report request covers.
    next_start_date: str
    # The report window size the run had reached, so a resumed run does not re-learn it.
    window_days: int | None = None


class AdMobAuthError(Exception):
    """The connected Google account's credentials were rejected or could not be refreshed."""


class AdMobReportTooLargeError(Exception):
    """One day of a report still fills the row budget after the sync split it as far as it can."""


def account_name(publisher_id: str) -> str:
    """The `accounts/{publisher_id}` resource name. Accepts a bare `pub-...` ID or a full resource name."""
    cleaned = (publisher_id or "").strip().strip("/")
    if cleaned.startswith("accounts/"):
        cleaned = cleaned[len("accounts/") :]
    return f"accounts/{cleaned}"


def _api_date(day: date) -> dict[str, int]:
    return {"year": day.year, "month": day.month, "day": day.day}


def _report_date(value: Any) -> Optional[datetime]:
    """A report `DATE` value (`YYYYMMDD`) as a UTC midnight datetime."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def _metric_columns(metric: str, value: dict[str, Any] | None) -> dict[str, Any]:
    column = metric.lower()
    value = value or {}
    if metric in MICROS_METRICS:
        micros = value.get("microsValue")
        micros_int = int(micros) if micros is not None else None
        return {
            column: micros_int / 1_000_000 if micros_int is not None else None,
            f"{column}_micros": micros_int,
        }
    if metric in INTEGER_METRICS:
        integer = value.get("integerValue")
        return {column: int(integer) if integer is not None else None}
    double = value.get("doubleValue")
    return {column: float(double) if double is not None else None}


def shape_report_row(row: dict[str, Any], report: AdMobReportConfig, currency_code: str | None) -> dict[str, Any]:
    """One report row as flat columns: a column per dimension and metric, plus the readable labels."""
    dimension_values = row.get("dimensionValues") or {}
    metric_values = row.get("metricValues") or {}
    shaped: dict[str, Any] = {}

    for dimension in report.dimensions:
        column = dimension.lower()
        value = dimension_values.get(dimension) or {}
        if dimension == "DATE":
            shaped[DATE_FIELD] = _report_date(value.get("value"))
            continue
        # The dimensions form the primary key, so a missing value becomes "" rather than null.
        shaped[column] = value.get("value") or ""
        if dimension in LABELLED_DIMENSIONS:
            shaped[f"{column}_name"] = value.get("displayLabel")

    for metric in report.metrics:
        shaped.update(_metric_columns(metric, metric_values.get(metric)))

    shaped["currency_code"] = currency_code
    return shaped


def report_rows(body: Any) -> list[dict[str, Any]]:
    """The raw data rows of a report response: a JSON array of one header, the rows and one footer."""
    if not isinstance(body, list):
        return []
    return [message["row"] for message in body if isinstance(message, dict) and isinstance(message.get("row"), dict)]


class AdMobClient:
    """Calls the AdMob API with the connected Google account's access token."""

    def __init__(
        self,
        access_token: str,
        refresh_access_token: AccessTokenRefresher | None = None,
        api_version: str = DEFAULT_API_VERSION,
        logger: FilteringBoundLogger | None = None,
        retry: bool = True,
    ) -> None:
        self._token = access_token
        self._refresh_access_token = refresh_access_token
        self._api_version = api_version
        self._logger = logger
        # The wizard calls the API inside a web request, which must fail fast rather than back off.
        self._retry = retry
        # The token rides the `Authorization` header, which the tracked transport scrubs. Report
        # bodies hold the customer's earnings, so they stay out of diagnostic HTTP samples.
        self._session = make_tracked_session(capture=False)

    def _url(self, path: str, params: dict[str, str] | None = None) -> str:
        url = f"{ADMOB_HOST}/{self._api_version}/{path}"
        return f"{url}?{urlencode(params)}" if params else url

    def request(self, method: str, path: str, params: dict[str, str] | None = None, body: Any = None) -> Any:
        if self._retry:
            return self._request_with_retry(method, path, params, body)
        return self._request_once(method, path, params, body)

    @vendor_retry()
    def _request_with_retry(self, method: str, path: str, params: dict[str, str] | None, body: Any) -> Any:
        return self._request_once(method, path, params, body)

    def _request_once(self, method: str, path: str, params: dict[str, str] | None, body: Any) -> Any:
        url = self._url(path, params)

        def _send(token: str) -> requests.Response:
            return self._session.request(
                method,
                url,
                json=body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

        response = _send(self._token)
        # Google access tokens last about an hour, so a long backfill can outlive one.
        if response.status_code == 401 and self._refresh_access_token is not None:
            self._token = self._refresh_access_token()
            response = _send(self._token)

        raise_for_retryable_status(response, vendor="AdMob", url=url)
        if not response.ok and self._logger is not None:
            self._logger.error(f"AdMob API error: status={response.status_code}, body={response.text[:500]}")
        raise_for_status_redacted(response, url=url)
        return response.json()

    def list_accounts(self) -> list[dict[str, Any]]:
        body = self.request("GET", "accounts")
        return (body.get("account") or []) if isinstance(body, dict) else []

    def get_account(self, publisher_id: str) -> dict[str, Any]:
        body = self.request("GET", account_name(publisher_id))
        return body if isinstance(body, dict) else {}

    def generate_report(
        self,
        publisher_id: str,
        report: AdMobReportConfig,
        start_day: date,
        end_day: date,
        filters: tuple[tuple[str, tuple[str, ...]], ...] = (),
        dimensions: tuple[str, ...] | None = None,
        metrics: tuple[str, ...] | None = None,
        max_rows: int = REPORT_ROW_BUDGET,
    ) -> list[dict[str, Any]]:
        """The raw rows of one report request."""
        spec: dict[str, Any] = {
            "dateRange": {"startDate": _api_date(start_day), "endDate": _api_date(end_day)},
            "dimensions": list(dimensions or report.dimensions),
            "metrics": list(metrics or report.metrics),
            "maxReportRows": max_rows,
        }
        if filters:
            spec["dimensionFilters"] = [
                {"dimension": dimension, "matchesAny": {"values": list(values)}} for dimension, values in filters
            ]
        body = self.request("POST", f"{account_name(publisher_id)}/{report.method}", body={"reportSpec": spec})
        return report_rows(body)


def _parse_start_date(start_date: str) -> Optional[date]:
    try:
        return date.fromisoformat(start_date.strip())
    except ValueError:
        return None


def validate_start_date(start_date: str | None) -> tuple[bool, Optional[str]]:
    if not start_date:
        return True, None
    parsed = _parse_start_date(start_date)
    if parsed is None:
        return False, f"Invalid start date '{start_date}'. Use the format YYYY-MM-DD."
    if parsed < date.fromisoformat(MIN_START_DATE):
        return False, f"Start date must be on or after {MIN_START_DATE}."
    if parsed > datetime.now(UTC).date():
        return False, "Start date can't be in the future."
    return True, None


def validate_credentials(
    access_token: str,
    publisher_id: str,
    start_date: str | None = None,
    api_version: str = DEFAULT_API_VERSION,
) -> tuple[bool, Optional[str]]:
    ok, message = validate_start_date(start_date)
    if not ok:
        return False, message

    try:
        AdMobClient(access_token, api_version=api_version, retry=False).get_account(publisher_id)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status == 401:
            return False, "Google rejected the connected account's credentials. Please reconnect the Google account."
        if status in (403, 404):
            return (
                False,
                "The connected Google account cannot read this AdMob account. Pick an account the Google "
                "account has access to, or reconnect with a Google account that has access.",
            )
        return False, f"Unexpected response from the AdMob API (status {status})."
    except Exception as e:
        return False, f"Could not reach the AdMob API ({e}). Please retry."

    return True, None


def resolve_start_day(
    start_date: str | None,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    today: date,
) -> date:
    """The first day to request: the stored watermark on an incremental run, else the user's
    start date, else a bounded first-sync horizon."""
    configured = _parse_start_date(start_date) if start_date else None
    floor = max(configured or today - timedelta(days=DEFAULT_LOOKBACK_DAYS), date.fromisoformat(MIN_START_DATE))
    floor_at = datetime(floor.year, floor.month, floor.day, tzinfo=UTC)
    return resolve_incremental_start(
        should_use_incremental_field,
        db_incremental_field_last_value,
        default=floor_at,
        floor=floor_at,
        now=datetime(today.year, today.month, today.day, tzinfo=UTC),
    ).date()


def _dimension_values(
    client: AdMobClient,
    publisher_id: str,
    report: AdMobReportConfig,
    day: date,
    filters: tuple[tuple[str, tuple[str, ...]], ...],
    dimension: str,
) -> tuple[str, ...]:
    """The values of one dimension that have rows on a day, from a small report on that dimension alone."""
    rows = client.generate_report(
        publisher_id, report, day, day, filters=filters, dimensions=(dimension,), metrics=SPLIT_VALUE_METRICS
    )
    values = {((row.get("dimensionValues") or {}).get(dimension) or {}).get("value") for row in rows}
    return tuple(sorted(value for value in values if value))


def _split_day(
    client: AdMobClient,
    publisher_id: str,
    report: AdMobReportConfig,
    day: date,
    filters: tuple[tuple[str, tuple[str, ...]], ...] = (),
    dimensions: tuple[str, ...] = SPLIT_DIMENSIONS,
) -> Iterator[list[dict[str, Any]]]:
    """The raw rows of a day that fills the row budget, fetched in slices that each fit it.

    The day is split by the values of `dimensions[0]`, halving the value list until each slice fits.
    A single value that still fills the budget is split by the next dimension. A slice that no
    dimension can split further is read with AdMob's own row limit, and the sync fails rather than
    keep a truncated slice.
    """
    if not dimensions:
        rows = client.generate_report(publisher_id, report, day, day, filters=filters, max_rows=ADMOB_MAX_REPORT_ROWS)
        if len(rows) >= ADMOB_MAX_REPORT_ROWS:
            raise AdMobReportTooLargeError(
                f"The AdMob {report.name} for {day.isoformat()} has more than {ADMOB_MAX_REPORT_ROWS} rows for "
                f"{dict(filters)}, so the sync cannot read it completely."
            )
        yield rows
        return
    dimension, rest = dimensions[0], dimensions[1:]
    yield from _fetch_slices(
        client,
        publisher_id,
        report,
        day,
        filters,
        dimension,
        rest,
        _dimension_values(client, publisher_id, report, day, filters, dimension),
        known_full=True,
    )


def _fetch_slices(
    client: AdMobClient,
    publisher_id: str,
    report: AdMobReportConfig,
    day: date,
    filters: tuple[tuple[str, tuple[str, ...]], ...],
    dimension: str,
    rest: tuple[str, ...],
    values: tuple[str, ...],
    known_full: bool = False,
) -> Iterator[list[dict[str, Any]]]:
    if not values:
        return
    if not known_full:
        rows = client.generate_report(publisher_id, report, day, day, filters=(*filters, (dimension, values)))
        if len(rows) < REPORT_ROW_BUDGET:
            yield rows
            return
    if len(values) > 1:
        middle = len(values) // 2
        yield from _fetch_slices(client, publisher_id, report, day, filters, dimension, rest, values[:middle])
        yield from _fetch_slices(client, publisher_id, report, day, filters, dimension, rest, values[middle:])
        return
    yield from _split_day(client, publisher_id, report, day, (*filters, (dimension, values)), rest)


def _chunks(
    slices: Iterable[list[dict[str, Any]]], report: AdMobReportConfig, currency_code: str | None
) -> Iterator[list[dict[str, Any]]]:
    for raw_rows in slices:
        for start in range(0, len(raw_rows), YIELD_CHUNK_ROWS):
            yield [shape_report_row(row, report, currency_code) for row in raw_rows[start : start + YIELD_CHUNK_ROWS]]


def _emit_window(
    chunks: Iterable[list[dict[str, Any]]],
    resumable_source_manager: ResumableSourceManager[AdMobResumeConfig],
    next_state: AdMobResumeConfig,
) -> Iterator[list[dict[str, Any]]]:
    """Yield a window's chunks, staging the cursor past the window only before the last one.

    A run that stops mid-window then resumes from the window's start, and the merge dedupes the
    rows it reads again.
    """
    pending: list[dict[str, Any]] | None = None
    for chunk in chunks:
        if pending:
            yield pending
        pending = chunk
    resumable_source_manager.save_state(next_state)
    if pending:
        yield pending
    else:
        resumable_source_manager.safe_point()


def get_report_rows(
    client: AdMobClient,
    publisher_id: str,
    report: AdMobReportConfig,
    start_date: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AdMobResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    today = datetime.now(UTC).date()
    # Today is partial in every time zone. Yesterday in UTC has started in every reporting time
    # zone, and the next run's lookback re-reads it.
    end_day = today - timedelta(days=1)
    cursor = resolve_start_day(start_date, should_use_incremental_field, db_incremental_field_last_value, today)
    window_days = REPORT_WINDOW_DAYS

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        resumed = _parse_start_date(resume.next_start_date)
        if resumed is not None:
            cursor = resumed
            window_days = min(max(resume.window_days or REPORT_WINDOW_DAYS, 1), REPORT_WINDOW_DAYS)
            logger.debug(f"AdMob: resuming {report.name} from {cursor.isoformat()}")

    # Report rows carry no currency, so stamp the account's earnings currency on each row.
    currency_code = client.get_account(publisher_id).get("currencyCode")

    while cursor <= end_day:
        window_end = min(cursor + timedelta(days=window_days - 1), end_day)
        span = (window_end - cursor).days + 1
        try:
            first = client.generate_report(publisher_id, report, cursor, window_end)
        except (requests.Timeout, requests.ConnectionError):
            # A report too big to generate in time times out or drops the connection after its retries.
            if span == 1:
                raise
            first = None

        if first is None or (len(first) >= REPORT_ROW_BUDGET and span > 1):
            # A full response is missing rows and a failed one has none, so ask again for a smaller window.
            window_days = max(1, span // 2)
            resumable_source_manager.safe_point()
            continue

        slices: Iterable[list[dict[str, Any]]] = (
            [first] if len(first) < REPORT_ROW_BUDGET else _split_day(client, publisher_id, report, cursor)
        )
        next_cursor = window_end + timedelta(days=1)
        # A window well under the budget can grow again, so one busy week does not slow the rest of a backfill.
        next_window_days = (
            min(window_days * 2, REPORT_WINDOW_DAYS) if len(first) < REPORT_ROW_BUDGET // 4 else window_days
        )
        yield from _emit_window(
            _chunks(slices, report, currency_code),
            resumable_source_manager,
            AdMobResumeConfig(next_start_date=next_cursor.isoformat(), window_days=next_window_days),
        )
        cursor = next_cursor
        window_days = next_window_days

    resumable_source_manager.clear_state()


def get_list_rows(
    client: AdMobClient,
    publisher_id: str,
    config: AdMobListConfig,
    resumable_source_manager: ResumableSourceManager[AdMobResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    params = {"pageSize": str(LIST_PAGE_SIZE)}
    while True:
        body = client.request("GET", f"{account_name(publisher_id)}/{config.method}", params=dict(params))
        items = (body.get(config.items_key) or []) if isinstance(body, dict) else []
        rows = [flatten_nested(item) for item in items if isinstance(item, dict)]
        if rows:
            yield rows
        else:
            resumable_source_manager.safe_point()

        page_token = body.get("nextPageToken") if isinstance(body, dict) else None
        if not page_token:
            return
        params["pageToken"] = page_token


def google_admob_source(
    access_token: str,
    refresh_access_token: AccessTokenRefresher | None,
    publisher_id: str,
    start_date: str | None,
    endpoint: str,
    api_version: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AdMobResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    def client() -> AdMobClient:
        return AdMobClient(
            access_token, refresh_access_token=refresh_access_token, api_version=api_version, logger=logger
        )

    if endpoint in ADMOB_LISTS:
        list_config = ADMOB_LISTS[endpoint]
        return SourceResponse(
            name=endpoint,
            items=lambda: get_list_rows(client(), publisher_id, list_config, resumable_source_manager),
            primary_keys=[list_config.primary_key],
        )

    report = ADMOB_REPORTS[endpoint]
    return SourceResponse(
        name=endpoint,
        items=lambda: get_report_rows(
            client=client(),
            publisher_id=publisher_id,
            report=report,
            start_date=start_date,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=report.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[DATE_FIELD],
    )
