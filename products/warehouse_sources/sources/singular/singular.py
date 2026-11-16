import json
import time
import datetime as dt
from collections.abc import Callable, Iterator
from itertools import batched
from typing import Any, Optional
from urllib.parse import parse_qsl, urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceResponse,
    frozen,
    make_tracked_session,
    request_deadline,
    stop_at_request_deadline,
)
from products.warehouse_sources.sources.singular.settings import (
    DAILY_REPORT,
    DATE_FIELD,
    FILTERS,
    FILTERS_PATH,
    FIXED_REPORTS,
    HISTORY_DAYS,
    LOOKUPS,
    SingularFixedReportConfig,
    SingularLookupConfig,
)

BASE_URL = "https://api.singular.net"
DAILY_REPORT_PATH = "/api/{api_version}/create_async_report"
REQUEST_TIMEOUT_SECONDS = 60
DOWNLOAD_TIMEOUT_SECONDS = 300
CREATE_MAX_ATTEMPTS = 5
# Singular allows one status call per report every 10 seconds.
REPORT_POLL_INTERVAL_SECONDS = 15
# Singular treats a report that is not done after 30 minutes as stuck and says to submit it again.
REPORT_POLL_MAX_ATTEMPTS = 30 * 60 // REPORT_POLL_INTERVAL_SECONDS
ROWS_PER_BATCH = 5000

# `get_non_retryable_errors` matches on these, so each one must stay the start of its message.
AUTH_ERROR = "Singular rejected the API key"
ACCESS_ERROR = "Singular denied access"
REQUEST_ERROR = "Singular rejected the request"
REPORT_FAILED_ERROR = "Singular could not generate the report"
QUOTA_ERROR = "Singular is still rate limiting this API key"
# `get_retryable_errors` matches on this one.
RETRYABLE_ERROR = "Singular request failed and can be retried"


class SingularRetryableError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(f"{RETRYABLE_ERROR}: {detail}")
        self.detail = detail


class SingularRateLimitError(SingularRetryableError):
    pass


class SingularNonRetryableError(Exception):
    pass


@frozen
class SingularResumeConfig:
    """The first day a retried run still has to fetch."""

    next_date: str


@frozen
class SingularReportQuery:
    dimensions: tuple[str, ...]
    metrics: tuple[str, ...]
    cohort_metrics: tuple[str, ...] = ()
    cohort_periods: tuple[str, ...] = ()
    extra_params: tuple[tuple[str, str], ...] = ()


def parse_field_list(value: Optional[str], default: tuple[str, ...] = ()) -> tuple[str, ...]:
    names = [name.strip() for name in (value or "").split(",")]
    # Singular rejects a request that names a field twice.
    return tuple(dict.fromkeys(name for name in names if name)) or default


def as_date(value: Any) -> Optional[dt.date]:
    """Read the stored `date` cursor, which arrives as a date, a datetime, or a YYYY-MM-DD string."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and value:
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def report_request_payload(query: SingularReportQuery, day: dt.date) -> dict[str, str]:
    payload = {
        "dimensions": ",".join(query.dimensions),
        "metrics": ",".join(query.metrics),
        "start_date": day.isoformat(),
        "end_date": day.isoformat(),
        "time_breakdown": "day",
        "format": "json",
    }
    if query.cohort_metrics:
        payload["cohort_metrics"] = ",".join(query.cohort_metrics)
    if query.cohort_periods:
        payload["cohort_periods"] = ",".join(query.cohort_periods)
    payload.update(query.extra_params)
    return payload


def report_rows(body: Any) -> list[dict[str, Any]]:
    # Singular does not document the downloaded file. Its synchronous API wraps the rows as
    # `value.results`, so accept that envelope, a bare `results` object, and a bare list.
    if isinstance(body, dict):
        body = body.get("value", body)
    if isinstance(body, dict):
        body = body.get("results")
    if not isinstance(body, list):
        raise ValueError("Singular report file has an unrecognized shape")
    return body


def _error_detail(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:500]
    value = body.get("value") if isinstance(body, dict) else None
    return value if isinstance(value, str) else response.text[:500]


def _response_value(response: requests.Response) -> dict[str, Any]:
    """Unwrap Singular's `{"status", "substatus", "value"}` envelope, or raise for a failed call."""
    status = response.status_code
    if status == 429:
        raise SingularRateLimitError(_error_detail(response))
    if status >= 500:
        raise SingularRetryableError(f"status={status}")
    if status == 401:
        raise SingularNonRetryableError(
            f"{AUTH_ERROR}. Copy the current key from Developer Tools > API Keys in Singular and update this source. "
            f"Singular said: {_error_detail(response)}"
        )
    if status == 403:
        raise SingularNonRetryableError(
            f"{ACCESS_ERROR}. Ask a Singular admin to let this API key view every dimension and metric in the "
            f"source settings, or remove the ones it cannot view. Singular said: {_error_detail(response)}"
        )

    value = None
    if response.ok:
        try:
            body = response.json()
        except ValueError:
            # A proxy page with a success status is not Singular's answer, so the call is worth repeating.
            raise SingularRetryableError(f"status={status} with a body that is not JSON") from None
        value = body.get("value") if isinstance(body, dict) else None
    if not isinstance(value, dict):
        raise SingularNonRetryableError(
            f"{REQUEST_ERROR}. Check the dimensions, metrics, and cohort settings of this source. "
            f"Singular said: {_error_detail(response)}"
        )
    return value


class SingularClient:
    def __init__(self, api_key: str, api_version: str) -> None:
        self.api_version = api_version
        self.session = make_tracked_session(headers={"Authorization": api_key}, redact_values=(api_key,))
        # A report status body carries the presigned download URL, so those calls stay out of
        # sample capture.
        self.status_session = make_tracked_session(
            headers={"Authorization": api_key}, redact_values=(api_key,), capture=False
        )
        # The transport retries only GETs, so the report POST needs its own bounded retry.
        self._create_retrying = Retrying(
            retry=retry_if_exception_type((SingularRetryableError, requests.ReadTimeout, requests.ConnectionError)),
            stop=stop_after_attempt(CREATE_MAX_ATTEMPTS) | stop_at_request_deadline(),
            wait=wait_exponential_jitter(initial=5, max=60),
            reraise=True,
        )

    def get(
        self,
        path: str,
        params: Optional[dict[str, str]] = None,
        capture: bool = True,
        timeout: int = REQUEST_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        session = self.session if capture else self.status_session
        return _response_value(session.get(f"{BASE_URL}{path}", params=params, timeout=timeout))

    def _post_report(self, path: str, query: SingularReportQuery, day: dt.date) -> dict[str, Any]:
        return _response_value(
            self.session.post(
                f"{BASE_URL}{path}", data=report_request_payload(query, day), timeout=REQUEST_TIMEOUT_SECONDS
            )
        )

    def create_report(self, query: SingularReportQuery, day: dt.date, path: str) -> str:
        path = path.format(api_version=self.api_version)
        try:
            with request_deadline():
                value = self._create_retrying(self._post_report, path, query, day)
        except SingularRateLimitError as error:
            # Singular does not document how it reports a used-up daily row quota. A 429 that
            # outlasts the retries is the closest signal, and waiting longer inside one run cannot
            # clear it, so it stops the sync instead of retrying the whole activity.
            raise SingularNonRetryableError(
                f"{QUOTA_ERROR} after several retries. If the account has used its daily row quota, sync again "
                f"tomorrow. To use fewer rows, remove dimensions or sync less often. Singular said: {error.detail}"
            ) from error

        report_id = value.get("report_id")
        if not report_id:
            raise SingularNonRetryableError(
                f"{REQUEST_ERROR}. Singular did not return a report ID for {day.isoformat()}: {json.dumps(value)}"
            )
        return str(report_id)

    def await_download_url(self, report_id: str, day: dt.date, safe_point: Callable[[], None]) -> str:
        status = None
        for _attempt in range(REPORT_POLL_MAX_ATTEMPTS):
            value = self.get(
                f"/api/{self.api_version}/get_report_status", params={"report_id": report_id}, capture=False
            )
            status = value.get("status")

            if status == "DONE" and value.get("download_url"):
                return str(value["download_url"])
            if status == "FAILED":
                # The report ID stays in the message because Singular support asks for it.
                raise SingularNonRetryableError(
                    f"{REPORT_FAILED_ERROR} for {day.isoformat()}. Singular said: {json.dumps(value)}"
                )

            # A worker that shuts down during a long wait hands the run over here.
            safe_point()
            time.sleep(REPORT_POLL_INTERVAL_SECONDS)

        raise SingularRetryableError(
            f"report {report_id} for {day.isoformat()} still {status} after the polling budget"
        )

    def download_report(self, url: str) -> list[dict[str, Any]]:
        # The file sits on presigned storage, so the session carries no API key, and the signing
        # values in the URL are masked in the request log.
        signing_values = tuple(value for _name, value in parse_qsl(urlsplit(url).query) if len(value) >= 8)
        session = make_tracked_session(redact_values=signing_values, capture=False)
        response = session.get(url, timeout=DOWNLOAD_TIMEOUT_SECONDS)
        if not response.ok:
            # `raise_for_status` would put the presigned URL in the error the user reads.
            raise SingularRetryableError(f"report download returned status={response.status_code}")
        return report_rows(response.json())


def validate_credentials(api_key: str, api_version: str) -> tuple[bool, Optional[str]]:
    try:
        SingularClient(api_key, api_version).get(LOOKUPS["custom_dimensions"].path)
    except SingularNonRetryableError as error:
        return False, str(error)
    except Exception:
        return False, "Could not reach Singular to check the API key. Try again in a few minutes."
    return True, None


def report_start_date(
    today: dt.date, db_incremental_field_last_value: Optional[Any], history_start: Optional[dt.datetime]
) -> dt.date:
    cursor = as_date(db_incremental_field_last_value)
    if cursor is not None:
        return cursor
    if history_start is not None:
        return history_start.date()
    return today - dt.timedelta(days=HISTORY_DAYS)


def _async_report_day(
    client: SingularClient,
    query: SingularReportQuery,
    path: str,
    safe_point: Callable[[], None],
) -> Callable[[dt.date], list[dict[str, Any]]]:
    def fetch(day: dt.date) -> list[dict[str, Any]]:
        report_id = client.create_report(query, day, path)
        url = client.await_download_url(report_id, day, safe_point)
        return client.download_report(url)

    return fetch


def _sync_report_day(
    client: SingularClient, query: SingularReportQuery, path: str
) -> Callable[[dt.date], list[dict[str, Any]]]:
    def fetch(day: dt.date) -> list[dict[str, Any]]:
        value = client.get(
            path.format(api_version=client.api_version),
            params=report_request_payload(query, day),
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
        )
        return report_rows(value)

    return fetch


def _fill_null_keys(rows: list[dict[str, Any]], key_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    # A null key never matches on merge, so the row would be inserted again on each sync.
    return [{**row, **{field: "" for field in key_fields if row.get(field) is None}} for row in rows]


def _report_rows(
    fetch_day: Callable[[dt.date], list[dict[str, Any]]],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SingularResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    history_start: Optional[dt.datetime],
    null_key_fields: tuple[str, ...] = (),
) -> Iterator[list[dict[str, Any]]]:
    today = dt.datetime.now(dt.UTC).date()
    day = report_start_date(today, db_incremental_field_last_value, history_start)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        day = max(day, dt.date.fromisoformat(resume.next_date))

    # Singular recommends one report per day when pulling daily data.
    while day <= today:
        rows = fetch_day(day)
        if null_key_fields:
            rows = _fill_null_keys(rows, null_key_fields)
        logger.debug(f"Singular report for {day.isoformat()} returned {len(rows)} rows")

        for chunk in batched(rows, ROWS_PER_BATCH, strict=False):
            yield [{**row, DATE_FIELD: day} for row in chunk]

        day += dt.timedelta(days=1)
        resumable_source_manager.save_state(SingularResumeConfig(next_date=day.isoformat()))
        if not rows:
            # A run of empty days on the synchronous report is a run of requests with no yield.
            resumable_source_manager.safe_point()


def _lookup_rows(client: SingularClient, config: SingularLookupConfig) -> Iterator[list[dict[str, Any]]]:
    rows = client.get(config.path).get(config.data_key) or []
    if rows:
        yield rows


def filter_rows(value: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the filters response to one row per dimension value."""
    rows: list[dict[str, Any]] = []
    for dimension in value.get("dimensions") or []:
        for item in dimension.get("values") or []:
            rows.append(
                {
                    "dimension": dimension.get("name"),
                    "dimension_display_name": dimension.get("display_name"),
                    # Value names mix numbers (OS codes) and strings (source names) across dimensions.
                    "name": str(item.get("name")),
                    "display_name": item.get("display_name"),
                }
            )
    return rows


def _filter_rows(client: SingularClient) -> Iterator[list[dict[str, Any]]]:
    rows = filter_rows(client.get(FILTERS_PATH.format(api_version=client.api_version)))
    if rows:
        yield rows


def fixed_report_query(config: SingularFixedReportConfig) -> SingularReportQuery:
    return SingularReportQuery(dimensions=config.dimensions, metrics=config.metrics, extra_params=config.params)


def _primary_keys(endpoint: str, query: SingularReportQuery) -> list[str]:
    if endpoint == DAILY_REPORT:
        return [DATE_FIELD, *query.dimensions]
    if endpoint in FIXED_REPORTS:
        return [DATE_FIELD, *FIXED_REPORTS[endpoint].dimensions]
    if endpoint == FILTERS:
        return ["dimension", "name"]
    return [LOOKUPS[endpoint].primary_key]


def singular_source(
    api_key: str,
    api_version: str,
    endpoint: str,
    query: SingularReportQuery,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SingularResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
    history_start: Optional[dt.datetime] = None,
) -> SourceResponse:
    is_report = endpoint == DAILY_REPORT or endpoint in FIXED_REPORTS

    def items() -> Iterator[list[dict[str, Any]]]:
        client = SingularClient(api_key, api_version)
        if endpoint == DAILY_REPORT:
            fetch_day = _async_report_day(client, query, DAILY_REPORT_PATH, resumable_source_manager.safe_point)
            return _report_rows(
                fetch_day, logger, resumable_source_manager, db_incremental_field_last_value, history_start
            )
        if endpoint in FIXED_REPORTS:
            report = FIXED_REPORTS[endpoint]
            report_query = fixed_report_query(report)
            fetch_day = (
                _async_report_day(client, report_query, report.path, resumable_source_manager.safe_point)
                if report.is_async
                else _sync_report_day(client, report_query, report.path)
            )
            return _report_rows(
                fetch_day,
                logger,
                resumable_source_manager,
                db_incremental_field_last_value,
                history_start,
                null_key_fields=report.dimensions,
            )
        if endpoint == FILTERS:
            return _filter_rows(client)
        return _lookup_rows(client, LOOKUPS[endpoint])

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=_primary_keys(endpoint, query),
        partition_mode="datetime" if is_report else None,
        partition_format="month" if is_report else None,
        partition_keys=[DATE_FIELD] if is_report else None,
        sort_mode="asc",
        supports_resume=is_report,
    )
