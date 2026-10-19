import csv
import codecs
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.settings import (
    APPLOVIN_API_BASE_URL,
    APPLOVIN_ENDPOINTS,
    APPLOVIN_MANAGEMENT_API_BASE_URL,
    MANAGEMENT_ENDPOINTS,
    MANAGEMENT_PAGE_SIZE,
    MAX_REQUEST_WINDOW_DAYS,
    OPERATION_LOG_WINDOW_DAYS,
    PRIMARY_KEYS,
    REPORT_LOOKBACK_DAYS,
    REPORT_PAGE_SIZE,
    REPORT_WINDOW_DAYS,
    USER_AD_REVENUE_APPS,
    USER_AD_REVENUE_BATCH_SIZE,
    USER_AD_REVENUE_ENDPOINT,
    USER_AD_REVENUE_LOOKBACK_DAYS,
    USER_AD_REVENUE_PATH,
    USER_AD_REVENUE_PRIMARY_KEYS,
    AppLovinEndpointConfig,
    AppLovinManagementEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.observer import redact_request_urls
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.url_utils import redact_literal_values
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

REQUEST_TIMEOUT_SECONDS = 120
VALIDATION_TIMEOUT_SECONDS = 30

# Matched by `AppLovinSource.get_non_retryable_errors`, so keep these stable.
AUTH_ERROR_PREFIX = "AppLovin denied the request"
BAD_REQUEST_ERROR_PREFIX = "AppLovin rejected the report request"
MANAGEMENT_AUTH_ERROR_PREFIX = "AppLovin denied the Campaign Management API request"
MANAGEMENT_CREDENTIALS_MISSING_PREFIX = "AppLovin Campaign Management API credentials are missing"
# Deliberately NOT registered as non-retryable: the tracked session already retried the request,
# and an upstream outage must not permanently disable the source.
TRANSIENT_ERROR_PREFIX = "AppLovin API error (retryable)"

_AUTH_STATUS_CODES = (401, 403)


class AppLovinAPIError(Exception):
    pass


def _utc_today() -> date:
    return datetime.now(tz=UTC).date()


def _redacted(message: str, api_key: str) -> str:
    """Strip the Report Key out of a message before it can reach a user-visible error.

    A transport error quotes the request URL, where the key is URL-encoded, so redact the
    raw, percent-encoded, and plus-encoded forms via the shared value-based masker.
    """
    return redact_literal_values(message, (api_key,)) if api_key else message


def _to_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def _body_code(body: Any, key: str = "code") -> Optional[int]:
    """AppLovin echoes its own status in the JSON body (`code`, or `status` on some endpoints); 200 means success."""
    if not isinstance(body, dict):
        return None
    try:
        return int(body[key])
    except (KeyError, TypeError, ValueError):
        return None


def _is_transient_status(status_code: int) -> bool:
    """Throttling and upstream failures, which the source must keep retrying."""
    return status_code == 429 or status_code >= 500


def _prefix_for_code(code: int) -> str:
    if code in _AUTH_STATUS_CODES:
        return AUTH_ERROR_PREFIX
    if _is_transient_status(code):
        return TRANSIENT_ERROR_PREFIX
    return BAD_REQUEST_ERROR_PREFIX


def _get(
    session: requests.Session, url: str, secret: str, timeout: int = REQUEST_TIMEOUT_SECONDS, stream: bool = False
) -> requests.Response:
    try:
        return session.get(url, timeout=timeout, stream=stream)
    except requests.RequestException as e:
        # `requests`/`urllib3` transport errors quote the full request URL, which can carry the
        # key as a query param. Re-raise redacted, and drop the cause so the original
        # (unredacted) message can't be surfaced through the exception chain.
        raise AppLovinAPIError(f"AppLovin request failed: {_redacted(str(e), secret)}") from None


def _raise_for_status(
    response: requests.Response, path: str, secret: str, auth_prefix: str = AUTH_ERROR_PREFIX
) -> None:
    if response.status_code in _AUTH_STATUS_CODES:
        raise AppLovinAPIError(f"{auth_prefix}: status={response.status_code}, endpoint={path}")

    if _is_transient_status(response.status_code):
        raise AppLovinAPIError(f"{TRANSIENT_ERROR_PREFIX}: status={response.status_code}, endpoint={path}")

    if not response.ok:
        raise AppLovinAPIError(
            f"{BAD_REQUEST_ERROR_PREFIX}: status={response.status_code}, endpoint={path}, "
            f"body={_redacted(response.text, secret)[:500]}"
        )


def _json_body(response: requests.Response, path: str, secret: str) -> Any:
    try:
        return response.json()
    except ValueError:
        raise AppLovinAPIError(
            f"{BAD_REQUEST_ERROR_PREFIX}: endpoint={path} returned a non-JSON body: "
            f"{_redacted(response.text, secret)[:500]}"
        ) from None


def _build_url(config: AppLovinEndpointConfig, api_key: str, start: date, end: date, offset: int) -> str:
    params: dict[str, Any] = {
        "api_key": api_key,
        "columns": ",".join(config.columns),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "format": "json",
        "limit": REPORT_PAGE_SIZE,
        "offset": offset,
        # Pin the order so limit/offset paging can't reshuffle rows between pages, and so rows
        # arrive oldest-first (`sort_mode="asc"` on the response).
        "sort_day": "ASC",
        **config.extra_params,
    }
    return f"{APPLOVIN_API_BASE_URL}{config.path}?{urlencode(params)}"


def _fetch_page(
    session: requests.Session,
    config: AppLovinEndpointConfig,
    api_key: str,
    start: date,
    end: date,
    offset: int,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    response = _get(session, _build_url(config, api_key, start, end, offset), api_key)
    _raise_for_status(response, config.path, api_key)
    body = _json_body(response, config.path, api_key)

    code = _body_code(body)
    if code is not None and code != 200:
        raise AppLovinAPIError(f"{_prefix_for_code(code)}: body code={code}, endpoint={config.path}")

    results = body.get("results") if isinstance(body, dict) else None
    if not isinstance(results, list):
        logger.debug(f"AppLovin: {config.name} returned no results list for {start.isoformat()}..{end.isoformat()}")
        return []

    return [row for row in results if isinstance(row, dict)]


@dataclasses.dataclass(frozen=True)
class AppLovinResumeConfig:
    # First day (YYYY-MM-DD) of the report window still being fetched.
    next_window_start: Optional[str] = None
    # `offset` of the next unfetched page within that window.
    next_offset: int = 0
    # Page number of the next unfetched Campaign Management list page.
    next_page: int = 0


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: "ResumableSourceManager[AppLovinResumeConfig]",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = APPLOVIN_ENDPOINTS[endpoint]
    session = make_tracked_session(redact_values=(api_key,))

    today = _utc_today()
    # The API refuses dates older than the request window, so clamp every start to it rather
    # than letting a stale watermark produce a guaranteed error.
    earliest = today - timedelta(days=MAX_REQUEST_WINDOW_DAYS - 1)

    start = earliest
    if should_use_incremental_field:
        watermark = _to_date(db_incremental_field_last_value)
        if watermark is not None:
            start = max(earliest, watermark - timedelta(days=REPORT_LOOKBACK_DAYS))

    offset = 0
    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None and resume_config.next_window_start:
        resumed = _to_date(resume_config.next_window_start)
        if resumed is not None and earliest <= resumed <= today and resumed >= start:
            start = resumed
            offset = resume_config.next_offset
            logger.debug(f"AppLovin: resuming {endpoint} from {start.isoformat()} offset {offset}")

    while start <= today:
        window_end = min(start + timedelta(days=REPORT_WINDOW_DAYS - 1), today)

        while True:
            rows = _fetch_page(session, config, api_key, start, window_end, offset, logger)
            if rows:
                yield rows

            # A short page means the window is exhausted: AppLovin returns an empty set once
            # `offset` passes the total row count.
            if len(rows) < REPORT_PAGE_SIZE:
                break

            offset += REPORT_PAGE_SIZE
            # Saved after yielding so a crash re-yields the in-flight page instead of skipping
            # it (the merge dedupes on the dimension primary key).
            resumable_source_manager.save_state(
                AppLovinResumeConfig(next_window_start=start.isoformat(), next_offset=offset)
            )

        start = window_end + timedelta(days=1)
        offset = 0
        if start <= today:
            resumable_source_manager.save_state(
                AppLovinResumeConfig(next_window_start=start.isoformat(), next_offset=0)
            )

    # The whole window is walked, so drop the checkpoint rather than leaving a later attempt to
    # resume from the final report window.
    resumable_source_manager.clear_state()


@frozen(order=True)
class AppLovinApp:
    package_name: str
    platform: str


def _user_ad_revenue_apps(
    session: requests.Session, api_key: str, day: date, logger: FilteringBoundLogger
) -> list[AppLovinApp]:
    """List the apps with MAX impressions on one day, in a stable order."""
    apps: set[AppLovinApp] = set()
    offset = 0
    while True:
        rows = _fetch_page(session, USER_AD_REVENUE_APPS, api_key, day, day, offset, logger)
        for row in rows:
            package_name, platform = row.get("package_name"), row.get("platform")
            if package_name and platform:
                apps.add(AppLovinApp(package_name=str(package_name), platform=str(platform).lower()))
        if len(rows) < REPORT_PAGE_SIZE:
            return sorted(apps)
        offset += REPORT_PAGE_SIZE


def _to_int(value: str) -> Optional[int]:
    try:
        return int(value)
    except ValueError:
        return None


def _to_decimal(value: str) -> Optional[Decimal]:
    try:
        return Decimal(value) if value.strip() else None
    except InvalidOperation:
        return None


def _normalize_csv_column(header: str) -> str:
    # The CSV headers vary in case and spacing between report versions ("User Id", " Ad Placement").
    return "_".join(header.strip().lower().split())


def _user_ad_revenue_report(
    session: requests.Session,
    api_key: str,
    day: date,
    app: AppLovinApp,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    package_name, platform = app.package_name, app.platform
    params = {
        "api_key": api_key,
        "date": day.isoformat(),
        "platform": platform,
        "application": package_name,
        "aggregated": "true",
    }
    response = _get(session, f"{APPLOVIN_API_BASE_URL}{USER_AD_REVENUE_PATH}?{urlencode(params)}", api_key)
    if response.status_code == 404:
        logger.debug(f"AppLovin: no user-level ad revenue report for {package_name} on {day.isoformat()}")
        return
    _raise_for_status(response, USER_AD_REVENUE_PATH, api_key)
    body = _json_body(response, USER_AD_REVENUE_PATH, api_key)

    status = _body_code(body, key="status")
    if status == 404:
        return
    if status is not None and status != 200:
        raise AppLovinAPIError(f"{_prefix_for_code(status)}: body status={status}, endpoint={USER_AD_REVENUE_PATH}")

    report_url = body.get("ad_revenue_report_url") if isinstance(body, dict) else None
    if not isinstance(report_url, str) or not report_url:
        return

    # The pre-signed link is a bearer credential for the report, so keep it out of request logs and errors.
    try:
        with redact_request_urls():
            download = session.get(report_url, timeout=REQUEST_TIMEOUT_SECONDS, stream=True)
    except requests.RequestException as e:
        raise AppLovinAPIError(
            f"{TRANSIENT_ERROR_PREFIX}: report download failed ({type(e).__name__}), endpoint={USER_AD_REVENUE_PATH}"
        ) from None

    with download:
        if not download.ok:
            # The download link is pre-signed and expires after an hour, so a failed download is
            # retried with a fresh link instead of disabling the source.
            raise AppLovinAPIError(
                f"{TRANSIENT_ERROR_PREFIX}: report download status={download.status_code}, endpoint={USER_AD_REVENUE_PATH}"
            )

        download.raw.decode_content = True
        # Read physical lines off the socket so quoted multi-line fields keep the terminators csv needs.
        reader = csv.reader(codecs.getreader("utf-8-sig")(download.raw))
        header = next(reader, None)
        if not header:
            return
        columns = [_normalize_csv_column(column) for column in header]

        batch: list[dict[str, Any]] = []
        for record in reader:
            if not any(record):
                continue
            row: dict[str, Any] = dict.fromkeys(USER_AD_REVENUE_PRIMARY_KEYS, "")
            row.update(zip(columns, record))
            row.update(day=day.isoformat(), package_name=package_name, platform=platform)
            if "impressions" in row:
                row["impressions"] = _to_int(row["impressions"])
            if "revenue" in row:
                row["revenue"] = _to_decimal(row["revenue"])
            batch.append(row)
            if len(batch) >= USER_AD_REVENUE_BATCH_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def get_user_ad_revenue_rows(
    api_key: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: "ResumableSourceManager[AppLovinResumeConfig]",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    session = make_tracked_session(redact_values=(api_key,))
    # The report response body carries the pre-signed download link, so it must never be sampled.
    report_session = make_tracked_session(redact_values=(api_key,), capture=False)

    today = _utc_today()
    earliest = today - timedelta(days=MAX_REQUEST_WINDOW_DAYS - 1)
    # A day's report is published eight hours after the UTC day ends, so today never has one.
    last_day = today - timedelta(days=1)

    start = earliest
    if should_use_incremental_field:
        watermark = _to_date(db_incremental_field_last_value)
        if watermark is not None:
            start = max(earliest, watermark - timedelta(days=USER_AD_REVENUE_LOOKBACK_DAYS))

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None and resume_config.next_window_start:
        resumed = _to_date(resume_config.next_window_start)
        if resumed is not None and start <= resumed <= last_day:
            start = resumed
            logger.debug(f"AppLovin: resuming {USER_AD_REVENUE_ENDPOINT} from {start.isoformat()}")

    day = start
    while day <= last_day:
        # Every earlier day is fully yielded, so a resume from this day re-reads only this day.
        resumable_source_manager.save_state(AppLovinResumeConfig(next_window_start=day.isoformat()))
        resumable_source_manager.safe_point()

        for app in _user_ad_revenue_apps(session, api_key, day, logger):
            yielded = False
            for rows in _user_ad_revenue_report(report_session, api_key, day, app, logger):
                yielded = True
                yield rows
            if not yielded:
                resumable_source_manager.safe_point()

        day += timedelta(days=1)

    resumable_source_manager.clear_state()


def _management_session(api_key: str) -> requests.Session:
    return make_tracked_session(headers={"Authorization": api_key}, redact_values=(api_key,))


def _fetch_management_page(
    session: requests.Session,
    config: AppLovinManagementEndpointConfig,
    api_key: str,
    account_id: str,
    params: dict[str, Any],
    timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    url = f"{APPLOVIN_MANAGEMENT_API_BASE_URL}{config.path}?{urlencode({'account_id': account_id, **params})}"
    response = _get(session, url, api_key, timeout=timeout)
    _raise_for_status(response, config.path, api_key, auth_prefix=MANAGEMENT_AUTH_ERROR_PREFIX)
    body = _json_body(response, config.path, api_key)

    # Every list endpoint returns a bare JSON array and an empty one past the last page.
    if not isinstance(body, list):
        raise AppLovinAPIError(f"{BAD_REQUEST_ERROR_PREFIX}: endpoint={config.path} did not return a JSON array")

    return [row for row in body if isinstance(row, dict)]


def get_management_list_rows(
    api_key: str,
    account_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: "ResumableSourceManager[AppLovinResumeConfig]",
) -> Iterator[list[dict[str, Any]]]:
    config = MANAGEMENT_ENDPOINTS[endpoint]
    session = _management_session(api_key)

    page = 1
    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None and resume_config.next_page > 1:
        page = resume_config.next_page
        logger.debug(f"AppLovin: resuming {endpoint} from page {page}")

    while True:
        rows = _fetch_management_page(
            session, config, api_key, account_id, {"page": page, "size": MANAGEMENT_PAGE_SIZE}
        )
        if len(rows) < MANAGEMENT_PAGE_SIZE:
            if rows:
                yield rows
            break

        page += 1
        resumable_source_manager.save_state(AppLovinResumeConfig(next_page=page))
        yield rows

    resumable_source_manager.clear_state()


def get_operation_log_rows(
    api_key: str,
    account_id: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: "ResumableSourceManager[AppLovinResumeConfig]",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = MANAGEMENT_ENDPOINTS["campaign_operation_logs"]
    session = _management_session(api_key)

    today = _utc_today()
    earliest = today - timedelta(days=OPERATION_LOG_WINDOW_DAYS - 1)

    start = earliest
    if should_use_incremental_field:
        watermark = _to_date(db_incremental_field_last_value)
        if watermark is not None:
            # Operations never change once logged, and the merge dedupes on `operation_id`.
            start = max(earliest, watermark)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None and resume_config.next_window_start:
        resumed = _to_date(resume_config.next_window_start)
        if resumed is not None and start <= resumed <= today:
            start = resumed
            logger.debug(f"AppLovin: resuming campaign_operation_logs from {start.isoformat()}")

    day = start
    while day <= today:
        rows: list[dict[str, Any]] = []
        page = 1
        while True:
            page_rows = _fetch_management_page(
                session,
                config,
                api_key,
                account_id,
                {
                    "start_date": day.isoformat(),
                    "end_date": day.isoformat(),
                    "page": page,
                    "size": MANAGEMENT_PAGE_SIZE,
                },
            )
            rows.extend(page_rows)
            if len(page_rows) < MANAGEMENT_PAGE_SIZE:
                break
            page += 1

        day += timedelta(days=1)
        resumable_source_manager.save_state(AppLovinResumeConfig(next_window_start=day.isoformat()))
        if rows:
            # The API returns a day's operations newest-first. Days are walked oldest-first, so
            # sorting each day makes `operation_time` only move forward (`sort_mode="asc"`).
            rows.sort(key=lambda row: str(row.get("operation_time") or ""))
            yield rows
        else:
            resumable_source_manager.safe_point()

    resumable_source_manager.clear_state()


def validate_management_credentials(api_key: str, account_id: str) -> bool:
    """Confirm the Campaign Management API key can read campaigns on the given account."""
    session = _management_session(api_key)
    try:
        _fetch_management_page(
            session,
            MANAGEMENT_ENDPOINTS["campaigns"],
            api_key,
            account_id,
            {"page": 1, "size": 1},
            timeout=VALIDATION_TIMEOUT_SECONDS,
        )
    except Exception:  # noqa: BLE001 — a credential probe must never raise out of source create
        return False
    return True


def validate_credentials(api_key: str) -> bool:
    """Confirm the Report Key is accepted by at least one reporting endpoint.

    A key belonging to a publisher-only account and one belonging to an advertiser-only account
    both authenticate against `/maxReport` and `/report`, so a single probe would reject a valid
    key for the other account shape. Probe both and accept the first success.
    """
    session = make_tracked_session(redact_values=(api_key,))
    today = _utc_today()

    for path, extra_params in (("/maxReport", {}), ("/report", {"report_type": "publisher"})):
        params: dict[str, Any] = {
            "api_key": api_key,
            "columns": "day,impressions",
            "start": today.isoformat(),
            "end": today.isoformat(),
            "format": "json",
            "limit": 1,
            **extra_params,
        }
        try:
            response = session.get(
                f"{APPLOVIN_API_BASE_URL}{path}?{urlencode(params)}", timeout=VALIDATION_TIMEOUT_SECONDS
            )
            if not response.ok:
                continue
            code = _body_code(response.json())
        except Exception:  # noqa: BLE001 — a credential probe must never raise out of source create
            continue

        if code is None or code == 200:
            return True

    return False


def applovin_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: "ResumableSourceManager[AppLovinResumeConfig]",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    campaign_api_key: Optional[str] = None,
    account_id: Optional[str] = None,
) -> SourceResponse:
    primary_keys = list(PRIMARY_KEYS[endpoint])

    if endpoint in MANAGEMENT_ENDPOINTS:
        if not campaign_api_key or not account_id:
            raise AppLovinAPIError(f"{MANAGEMENT_CREDENTIALS_MISSING_PREFIX}: endpoint={endpoint}")
        management_config = MANAGEMENT_ENDPOINTS[endpoint]
        management_api_key, management_account_id = campaign_api_key, account_id

        def management_items() -> Iterator[list[dict[str, Any]]]:
            if endpoint == "campaign_operation_logs":
                return get_operation_log_rows(
                    api_key=management_api_key,
                    account_id=management_account_id,
                    logger=logger,
                    resumable_source_manager=resumable_source_manager,
                    should_use_incremental_field=should_use_incremental_field,
                    db_incremental_field_last_value=db_incremental_field_last_value,
                )
            return get_management_list_rows(
                api_key=management_api_key,
                account_id=management_account_id,
                endpoint=endpoint,
                logger=logger,
                resumable_source_manager=resumable_source_manager,
            )

        return SourceResponse(
            name=endpoint,
            items=management_items,
            primary_keys=primary_keys,
            partition_mode="datetime" if management_config.partition_key else None,
            partition_keys=[management_config.partition_key] if management_config.partition_key else None,
            sort_mode="asc",
        )

    if endpoint == USER_AD_REVENUE_ENDPOINT:
        return SourceResponse(
            name=endpoint,
            items=lambda: get_user_ad_revenue_rows(
                api_key=api_key,
                logger=logger,
                resumable_source_manager=resumable_source_manager,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            ),
            primary_keys=primary_keys,
            partition_mode="datetime",
            partition_keys=["day"],
            # Days are walked oldest-first, and every row of a day carries that day.
            sort_mode="asc",
        )

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
        primary_keys=primary_keys,
        partition_count=1,
        partition_size=1,
        # Windows are walked oldest-first and each request pins `sort_day=ASC`, so `day` only
        # ever moves forward; the restatement re-pull happens below the saved watermark and
        # merges on the dimension primary key.
        sort_mode="asc",
    )
