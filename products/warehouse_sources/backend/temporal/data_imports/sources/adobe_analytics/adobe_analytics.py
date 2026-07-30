import re
import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.adobe_analytics.settings import (
    ADOBE_ANALYTICS_ENDPOINTS,
    DEFAULT_REPORT_DIMENSION,
    DEFAULT_REPORT_METRICS,
    METADATA_PAGE_SIZE,
    REPORT_ENDPOINT,
    REPORT_PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# Adobe IMS issues the access token for OAuth Server-to-Server credentials. JWT ("Service
# Account") credentials were retired on 2025-06-30, so this is the only server-side grant left.
IMS_TOKEN_URL = "https://ims-na1.adobelogin.com/ims/token/v3"
IMS_SCOPES = "openid,AdobeID,read_organizations,additional_info.projectedProductContext"

ANALYTICS_HOST = "https://analytics.adobe.io"
DISCOVERY_URL = f"{ANALYTICS_HOST}/discovery/me"

# Adobe terminates its own requests at 60s.
REQUEST_TIMEOUT_SECONDS = 60
# Hard, non-raisable throttle of 12 requests per 6 seconds per user.
MIN_REQUEST_INTERVAL_SECONDS = 0.5
# Adobe restates recent report data, so each incremental run re-pulls a trailing window.
INCREMENTAL_LOOKBACK_DAYS = 1
DEFAULT_BACKFILL_DAYS = 90
# The report stream walks one day per request, so an unbounded start date would issue
# hundreds of thousands of sequential calls. Cap the earliest day we'll backfill.
MAX_BACKFILL_DAYS = 365 * 3
# Guard against a report whose paging never signals completion.
MAX_REPORT_PAGES = 200


@dataclasses.dataclass
class AdobeAnalyticsResumeConfig:
    # Metadata listings resume on a page number; the report stream resumes on the day
    # window it was mid-way through plus that day's page.
    page: int = 0
    next_date: Optional[str] = None


class AdobeAnalyticsClient:
    """Token-minting, throttled client for the Adobe Analytics 2.0 API."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        logger: FilteringBoundLogger,
        global_company_id: Optional[str] = None,
        min_request_interval: float = MIN_REQUEST_INTERVAL_SECONDS,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._logger = logger
        self._global_company_id = global_company_id or None
        self._min_request_interval = min_request_interval
        self._last_request_at: Optional[float] = None
        self._token: Optional[str] = None
        self._session = make_tracked_session(redact_values=(client_secret,))
        # The token exchange body carries the client secret and the response carries a live
        # bearer token, neither of which the name-based sample scrubbers recognise.
        self._auth_session = make_tracked_session(redact_values=(client_secret,), capture=False)

    def _pace(self) -> None:
        if self._min_request_interval <= 0:
            return
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self._min_request_interval:
                time.sleep(self._min_request_interval - elapsed)
        self._last_request_at = time.monotonic()

    def _mint_token(self) -> str:
        response = self._auth_session.post(
            IMS_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "scope": IMS_SCOPES,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            raise ValueError("Adobe IMS did not return an access token")
        return str(token)

    def _access_token(self) -> str:
        if self._token is None:
            self._token = self._mint_token()
        return self._token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token()}",
            "x-api-key": self._client_id,
            "Accept": "application/json",
        }

    def request(
        self,
        method: str,
        url: str,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
    ) -> requests.Response:
        def _do() -> requests.Response:
            self._pace()
            if method == "POST":
                return self._session.post(
                    url, headers=self._headers(), params=params, json=json_body, timeout=REQUEST_TIMEOUT_SECONDS
                )
            return self._session.get(url, headers=self._headers(), params=params, timeout=REQUEST_TIMEOUT_SECONDS)

        response = _do()
        # IMS access tokens last ~24h; re-mint once if a long sync outlives one.
        if response.status_code == 401:
            self._token = None
            response = _do()

        if not response.ok:
            self._logger.error(
                f"Adobe Analytics API error: status={response.status_code}, body={response.text}, url={url}"
            )
            response.raise_for_status()

        return response

    def resolve_global_company_id(self) -> str:
        """Return the configured global company id, discovering it from /discovery/me if absent."""
        if self._global_company_id:
            return self._global_company_id

        payload = self.request("GET", DISCOVERY_URL).json()
        for org in payload.get("imsOrgs") or []:
            for company in org.get("companies") or []:
                company_id = company.get("globalCompanyId")
                if company_id:
                    self._global_company_id = str(company_id)
                    return self._global_company_id

        raise ValueError(
            "Could not find a global company ID for these credentials. Check that the Analytics API is added "
            "to your Adobe Developer Console project and that the credential has a product profile assigned."
        )

    @property
    def base_url(self) -> str:
        return f"{ANALYTICS_HOST}/api/{self.resolve_global_company_id()}"

    def get_json(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        return self.request("GET", f"{self.base_url}{path}", params=params).json()

    def post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        payload = self.request("POST", f"{self.base_url}{path}", json_body=body).json()
        return payload if isinstance(payload, dict) else {}


def _today() -> date:
    return datetime.now(UTC).date()


def parse_date(value: Any) -> Optional[date]:
    """Coerce a config string or incremental watermark into a UTC calendar date."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def parse_metrics(raw: Optional[str]) -> list[str]:
    metrics = [metric.strip() for metric in (raw or DEFAULT_REPORT_METRICS).split(",")]
    metrics = [metric for metric in metrics if metric]
    if metrics:
        return metrics
    return [metric.strip() for metric in DEFAULT_REPORT_METRICS.split(",")]


def metric_column_names(metric_ids: list[str]) -> list[str]:
    """Map Adobe metric ids onto stable, warehouse-safe column names."""
    names: list[str] = []
    seen: dict[str, int] = {}
    for metric_id in metric_ids:
        base = re.sub(r"[^0-9a-zA-Z_]", "_", metric_id.rsplit("/", 1)[-1]) or "metric"
        count = seen.get(base, 0)
        seen[base] = count + 1
        names.append(base if count == 0 else f"{base}_{count + 1}")
    return names


def resolve_window(
    start_date: Optional[str],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    today: date,
) -> tuple[date, date]:
    earliest = today - timedelta(days=MAX_BACKFILL_DAYS)

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        last_value = parse_date(db_incremental_field_last_value)
        if last_value is not None:
            return max(min(last_value - timedelta(days=INCREMENTAL_LOOKBACK_DAYS), today), earliest), today

    configured = parse_date(start_date)
    if configured is not None:
        return max(min(configured, today), earliest), today

    return today - timedelta(days=DEFAULT_BACKFILL_DAYS), today


def build_report_body(
    report_suite_id: str, dimension: str, metric_ids: list[str], day: date, page: int
) -> dict[str, Any]:
    next_day = day + timedelta(days=1)
    return {
        "rsid": report_suite_id,
        "globalFilters": [
            {
                "type": "dateRange",
                "dateRange": f"{day.isoformat()}T00:00:00.000/{next_day.isoformat()}T00:00:00.000",
            }
        ],
        "metricContainer": {
            "metrics": [{"columnId": str(index), "id": metric_id} for index, metric_id in enumerate(metric_ids)]
        },
        "dimension": dimension,
        "settings": {"countRepeatInstances": True, "limit": REPORT_PAGE_SIZE, "page": page},
    }


def report_rows(
    payload: dict[str, Any], report_suite_id: str, day: date, dimension: str, metric_columns: list[str]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in payload.get("rows") or []:
        data = row.get("data") or []
        record: dict[str, Any] = {
            "rsid": report_suite_id,
            "date": day.isoformat(),
            "dimension": dimension,
            "item_id": str(row.get("itemId", "")),
            "value": row.get("value"),
        }
        for index, column in enumerate(metric_columns):
            record[column] = data[index] if index < len(data) else None
        rows.append(record)
    return rows


def _metadata_batches(
    client: AdobeAnalyticsClient,
    endpoint: str,
    report_suite_id: str,
    manager: ResumableSourceManager[AdobeAnalyticsResumeConfig],
    resume: Optional[AdobeAnalyticsResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = ADOBE_ANALYTICS_ENDPOINTS[endpoint]
    params: dict[str, Any] = {}
    if config.report_suite_param:
        params[config.report_suite_param] = report_suite_id

    if config.data_key is None:
        # `/dimensions` and `/metrics` return the whole catalog as a bare array, and their
        # rows carry no report suite of their own.
        payload = client.get_json(config.path, params)
        items = [{**item, "rsid": report_suite_id} for item in (payload or [])]
        if items:
            yield items
        manager.clear_state()
        return

    page = resume.page if resume is not None else 0
    while True:
        payload = client.get_json(config.path, {**params, "limit": METADATA_PAGE_SIZE, "page": page})
        items = list((payload or {}).get(config.data_key) or [])
        if items:
            yield items

        if not items or bool((payload or {}).get("lastPage")):
            break

        page += 1
        # Save state AFTER yielding so a crash re-yields the last page (merge dedupes on
        # primary key) rather than skipping it.
        manager.save_state(AdobeAnalyticsResumeConfig(page=page))

    manager.clear_state()


def _report_batches(
    client: AdobeAnalyticsClient,
    report_suite_id: str,
    dimension: str,
    metric_ids: list[str],
    start: date,
    end: date,
    manager: ResumableSourceManager[AdobeAnalyticsResumeConfig],
    resume: Optional[AdobeAnalyticsResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    metric_columns = metric_column_names(metric_ids)

    current = start
    page = 0
    if resume is not None and resume.next_date:
        resumed = parse_date(resume.next_date)
        if resumed is not None and start <= resumed <= end:
            current = resumed
            page = resume.page

    while current <= end:
        while True:
            payload = client.post_json(
                "/reports", build_report_body(report_suite_id, dimension, metric_ids, current, page)
            )
            rows = report_rows(payload, report_suite_id, current, dimension, metric_columns)
            if rows:
                yield rows

            total_pages = payload.get("totalPages")
            complete = (
                not rows or bool(payload.get("lastPage")) or (isinstance(total_pages, int) and page + 1 >= total_pages)
            )
            if not complete and page + 1 >= MAX_REPORT_PAGES:
                logger.warning(
                    f"Adobe Analytics report page cap reached, truncating the day: "
                    f"rsid={report_suite_id}, date={current.isoformat()}"
                )
                break
            if complete:
                break

            page += 1
            manager.save_state(AdobeAnalyticsResumeConfig(page=page, next_date=current.isoformat()))

        current += timedelta(days=1)
        page = 0
        if current <= end:
            manager.save_state(AdobeAnalyticsResumeConfig(page=0, next_date=current.isoformat()))

    manager.clear_state()


def validate_credentials(
    client_id: str, client_secret: str, global_company_id: Optional[str], logger: FilteringBoundLogger
) -> tuple[bool, Optional[str]]:
    """Mint a token and confirm the credential can reach the Analytics API."""
    client = AdobeAnalyticsClient(client_id, client_secret, logger, global_company_id)
    try:
        client.resolve_global_company_id()
    except requests.HTTPError:
        return False, "Adobe Analytics rejected the credentials. Check the client ID and secret."
    except ValueError as e:
        return False, str(e)
    except Exception:
        return False, "Could not reach Adobe Analytics. Please try again."

    try:
        client.get_json("/collections/suites", {"limit": 1, "page": 0})
    except Exception:
        return False, (
            "Adobe Analytics denied access to your report suites. Check that the Analytics API is added to "
            "your Adobe Developer Console project and that the credential has a product profile assigned."
        )

    return True, None


def get_rows(
    client_id: str,
    client_secret: str,
    global_company_id: Optional[str],
    report_suite_id: str,
    report_dimension: Optional[str],
    report_metrics: Optional[str],
    start_date: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AdobeAnalyticsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    client = AdobeAnalyticsClient(client_id, client_secret, logger, global_company_id)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if endpoint != REPORT_ENDPOINT:
        yield from _metadata_batches(client, endpoint, report_suite_id, resumable_source_manager, resume)
        return

    start, end = resolve_window(
        start_date,
        should_use_incremental_field,
        db_incremental_field_last_value,
        _today(),
    )
    yield from _report_batches(
        client,
        report_suite_id,
        (report_dimension or DEFAULT_REPORT_DIMENSION).strip() or DEFAULT_REPORT_DIMENSION,
        parse_metrics(report_metrics),
        start,
        end,
        resumable_source_manager,
        resume,
        logger,
    )


def adobe_analytics_source(
    client_id: str,
    client_secret: str,
    global_company_id: Optional[str],
    report_suite_id: str,
    report_dimension: Optional[str],
    report_metrics: Optional[str],
    start_date: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AdobeAnalyticsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = ADOBE_ANALYTICS_ENDPOINTS[endpoint]
    is_report = endpoint == REPORT_ENDPOINT

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            client_id=client_id,
            client_secret=client_secret,
            global_company_id=global_company_id,
            report_suite_id=report_suite_id,
            report_dimension=report_dimension,
            report_metrics=report_metrics,
            start_date=start_date,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_key,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if is_report else None,
        partition_format="month" if is_report else None,
        partition_keys=["date"] if is_report else None,
        # Report day windows are walked oldest-first; metadata listings are single-shot.
        sort_mode="asc",
    )
