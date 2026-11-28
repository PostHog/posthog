from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.sources.google_admob.settings import (
    ADMOB_HOST,
    ADMOB_LISTS,
    ADMOB_REPORTS,
    DATE_FIELD,
    DEFAULT_LOOKBACK_DAYS,
    LIST_PAGE_SIZE,
    MAX_REPORT_ROWS,
    MIN_START_DATE,
    REPORT_WINDOW_DAYS,
    AdMobListConfig,
    AdMobReportConfig,
)
from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceResponse,
    coerce_date,
    flatten_nested,
    frozen,
    make_tracked_session,
    raise_for_retryable_status,
    raise_for_status_redacted,
    vendor_retry,
)

REQUEST_TIMEOUT_SECONDS = 300
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


class AdMobAuthError(Exception):
    """The connected Google account's credentials were rejected or could not be refreshed."""


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


def rows_from_report(body: Any, report: AdMobReportConfig, currency_code: str | None) -> list[dict[str, Any]]:
    """The data rows of a report response: a JSON array of one header, the rows and one footer."""
    if not isinstance(body, list):
        return []
    return [
        shape_report_row(message["row"], report, currency_code)
        for message in body
        if isinstance(message, dict) and isinstance(message.get("row"), dict)
    ]


class AdMobClient:
    """Calls the AdMob API with the connected Google account's access token."""

    def __init__(
        self,
        access_token: str,
        refresh_access_token: AccessTokenRefresher | None = None,
        api_version: str = DEFAULT_API_VERSION,
        logger: FilteringBoundLogger | None = None,
    ) -> None:
        self._token = access_token
        self._refresh_access_token = refresh_access_token
        self._api_version = api_version
        self._logger = logger
        # The token rides the `Authorization` header, which the tracked transport scrubs. Report
        # bodies hold the customer's earnings, so they stay out of diagnostic HTTP samples.
        self._session = make_tracked_session(capture=False)

    def _url(self, path: str, params: dict[str, str] | None = None) -> str:
        url = f"{ADMOB_HOST}/{self._api_version}/{path}"
        return f"{url}?{urlencode(params)}" if params else url

    @vendor_retry()
    def request(self, method: str, path: str, params: dict[str, str] | None = None, body: Any = None) -> Any:
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

    def generate_report(self, publisher_id: str, report: AdMobReportConfig, start_day: date, end_day: date) -> Any:
        spec = {
            "dateRange": {"startDate": _api_date(start_day), "endDate": _api_date(end_day)},
            "dimensions": list(report.dimensions),
            "metrics": list(report.metrics),
            "maxReportRows": MAX_REPORT_ROWS,
        }
        return self.request("POST", f"{account_name(publisher_id)}/{report.method}", body={"reportSpec": spec})


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
        AdMobClient(access_token, api_version=api_version).get_account(publisher_id)
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

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        watermark = coerce_date(db_incremental_field_last_value)
        if watermark is not None:
            return max(floor, watermark)

    return floor


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

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        resumed = coerce_date(resume.next_start_date)
        if resumed is not None:
            cursor = resumed
            logger.debug(f"AdMob: resuming {report.name} from {cursor.isoformat()}")

    # Report rows carry no currency, so stamp the account's earnings currency on each row.
    currency_code = client.get_account(publisher_id).get("currencyCode")

    window_days = REPORT_WINDOW_DAYS
    while cursor <= end_day:
        window_end = min(cursor + timedelta(days=window_days - 1), end_day)
        rows = rows_from_report(client.generate_report(publisher_id, report, cursor, window_end), report, currency_code)

        if len(rows) >= MAX_REPORT_ROWS:
            span = (window_end - cursor).days + 1
            if span > 1:
                # AdMob drops the rows past the limit, so ask again for a smaller window.
                window_days = max(1, span // 2)
                resumable_source_manager.safe_point()
                continue
            logger.warning(
                f"AdMob: {report.name} for {cursor.isoformat()} reached the {MAX_REPORT_ROWS} row limit, "
                "so rows past the limit are missing"
            )

        cursor = window_end + timedelta(days=1)
        resumable_source_manager.save_state(AdMobResumeConfig(next_start_date=cursor.isoformat()))
        if rows:
            yield rows
        else:
            resumable_source_manager.safe_point()

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
