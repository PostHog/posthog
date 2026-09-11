import io
import gzip
import json
import time
import datetime as dt
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import parse_qsl, urlparse, urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_ads.settings import (
    AMAZON_ADS_ENDPOINTS,
    AmazonAdsReportConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

AMAZON_ADS_HOSTS = {
    "na": "https://advertising-api.amazon.com",
    "eu": "https://advertising-api-eu.amazon.com",
    "fe": "https://advertising-api-fe.amazon.com",
}
# Login with Amazon token endpoint is global.
LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
PAGE_SIZE = 500
REQUEST_TIMEOUT_SECONDS = 120
MAX_RETRY_ATTEMPTS = 5

# The vendor's own examples send this on both the create and the status call, and no Accept.
REPORT_MEDIA_TYPE = "application/vnd.createasyncreportrequest.v3+json"
REPORT_POLL_INTERVAL_SECONDS = 30
REPORT_POLL_MAX_ATTEMPTS = 40
REPORT_DOWNLOAD_TIMEOUT_SECONDS = 300
REPORT_ROWS_PER_BATCH = 2000
# The generated file sits on presigned Amazon storage rather than the API host. Pinning the host
# keeps a tampered `url` from pointing the download somewhere else.
REPORT_URL_HOST_SUFFIXES = (".amazonaws.com", ".amazon.com")


class AmazonAdsRetryableError(Exception):
    pass


class AmazonAdsReportError(Exception):
    """Amazon finished generating a report and marked it failed."""


@frozen
class ReportWindow:
    start: dt.date
    end: dt.date


@frozen
class AmazonAdsResumeConfig:
    """The report Amazon is generating right now, so a retried activity re-polls it.

    Asking twice for a report with identical parameters is answered with a 425 until the first
    one finishes, so a retry that starts over would wait out the report it abandoned.
    """

    profile_id: str
    window_start: str
    report_id: str


def _get_session(
    client_secret: str,
    refresh_token: str,
    client_id: str,
    capture: bool = True,
    extra_redact: tuple[str, ...] = (),
) -> requests.Session:
    return make_tracked_session(
        headers={"Amazon-Advertising-API-ClientId": client_id},
        redact_values=(client_secret, refresh_token, *extra_redact),
        capture=capture,
    )


def presigned_secret_values(url: str) -> tuple[str, ...]:
    """The signing material AWS puts in a presigned URL.

    Anyone holding it can download the report until it expires, and the shared scrubber
    masks query values by name, which does not cover `X-Amz-Signature` and its siblings.
    """
    return tuple(
        value for name, value in parse_qsl(urlsplit(url).query) if name.lower().startswith("x-amz-") and len(value) >= 8
    )


def _base_url(region: str) -> str:
    host = AMAZON_ADS_HOSTS.get(region)
    if host is None:
        raise ValueError(f"Invalid Amazon Ads region: {region}")
    return host


def _mint_token(session: requests.Session, client_id: str, client_secret: str, refresh_token: str) -> str:
    """Exchange the LWA refresh token for a ~1h access token."""
    response = session.post(
        LWA_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def validate_credentials(region: str, client_id: str, client_secret: str, refresh_token: str) -> bool:
    """Confirm the LWA credentials are valid by minting a token and listing profiles."""
    try:
        _base_url(region)
        session = _get_session(client_secret, refresh_token, client_id)
        token = _mint_token(session, client_id, client_secret, refresh_token)
        response = session.get(
            f"{_base_url(region)}/v2/profiles",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        return response.status_code == 200
    except Exception:
        return False


def as_report_date(value: Any) -> Optional[dt.date]:
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


def report_windows(start: dt.date, end: dt.date, max_window_days: int) -> Iterator[ReportWindow]:
    while start <= end:
        window_end = min(start + dt.timedelta(days=max_window_days - 1), end)
        yield ReportWindow(start=start, end=window_end)
        start = window_end + dt.timedelta(days=1)


def report_request_body(report: AmazonAdsReportConfig, start: dt.date, end: dt.date) -> dict[str, Any]:
    return {
        "name": f"PostHog {report.report_type_id} {start.isoformat()} to {end.isoformat()}",
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "configuration": {
            "adProduct": report.ad_product,
            "groupBy": list(report.group_by),
            "columns": list(report.columns),
            "reportTypeId": report.report_type_id,
            "timeUnit": report.time_unit,
            "format": "GZIP_JSON",
        },
    }


def download_report_rows(url: str, client_id: str, client_secret: str, refresh_token: str) -> list[dict[str, Any]]:
    host = (urlparse(url).hostname or "").lower()
    if not host.endswith(REPORT_URL_HOST_SUFFIXES):
        raise ValueError(f"Amazon Ads report download URL points outside Amazon: host={host}")

    session = _get_session(
        client_secret, refresh_token, client_id, capture=False, extra_redact=presigned_secret_values(url)
    )
    response = session.get(url, timeout=REPORT_DOWNLOAD_TIMEOUT_SECONDS)
    response.raise_for_status()
    with gzip.GzipFile(fileobj=io.BytesIO(response.content)) as unzipped:
        rows = json.load(unzipped)

    return rows if isinstance(rows, list) else []


def get_rows(
    region: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: Optional[ResumableSourceManager[AmazonAdsResumeConfig]] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> Iterator[list[dict[str, Any]]]:
    config = AMAZON_ADS_ENDPOINTS[endpoint]
    session = _get_session(client_secret, refresh_token, client_id)
    # A report status body carries the presigned download URL, so those calls stay out of
    # sample capture.
    report_session = _get_session(client_secret, refresh_token, client_id, capture=False)
    base_url = _base_url(region)
    token = _mint_token(session, client_id, client_secret, refresh_token)

    @retry(
        retry=retry_if_exception_type((AmazonAdsRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=120),
        reraise=True,
    )
    def request(
        method: str,
        path: str,
        profile_id: Optional[str] = None,
        body: Optional[dict[str, Any]] = None,
        extra_headers: Optional[dict[str, str]] = None,
        http: Optional[requests.Session] = None,
    ) -> requests.Response:
        nonlocal token
        url = f"{base_url}{path}"
        client = http if http is not None else session

        def _do() -> requests.Response:
            headers: dict[str, str] = {"Authorization": f"Bearer {token}"}
            if profile_id is not None:
                headers["Amazon-Advertising-API-Scope"] = profile_id
            if config.media_type is not None and method == "POST":
                headers["Content-Type"] = config.media_type
                headers["Accept"] = config.media_type
            if extra_headers is not None:
                headers.update(extra_headers)
            if method == "POST":
                return client.post(url, json=body or {}, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
            return client.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        response = _do()
        # Access tokens last ~1h; re-mint once if the sync outlives one.
        if response.status_code == 401:
            token = _mint_token(session, client_id, client_secret, refresh_token)
            response = _do()

        # 425 says an identical report is still generating, so the wait is worth repeating.
        if response.status_code in (425, 429) or response.status_code >= 500:
            raise AmazonAdsRetryableError(f"Amazon Ads API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Amazon Ads API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response

    def list_profiles() -> list[dict[str, Any]]:
        body = request("GET", "/v2/profiles").json()
        return body if isinstance(body, list) else []

    def await_report_url(report: AmazonAdsReportConfig, profile_id: str, report_id: str) -> Optional[str]:
        status = None
        for _attempt in range(REPORT_POLL_MAX_ATTEMPTS):
            body = request(
                "GET",
                f"{config.path}/{report_id}",
                profile_id=profile_id,
                extra_headers={"Content-Type": REPORT_MEDIA_TYPE},
                http=report_session,
            ).json()
            status = body.get("status")

            if status == "COMPLETED":
                return body.get("url")
            if status == "FAILED":
                raise AmazonAdsReportError(
                    f"Amazon Ads could not generate the {report.report_type_id} report: {body.get('failureReason')}"
                )

            time.sleep(REPORT_POLL_INTERVAL_SECONDS)

        raise AmazonAdsRetryableError(
            f"Amazon Ads {report.report_type_id} report {report_id} still {status} after the polling budget"
        )

    def report_rows(report: AmazonAdsReportConfig, profile_ids: list[str]) -> Iterator[list[dict[str, Any]]]:
        today = dt.datetime.now(dt.UTC).date()
        earliest = today - dt.timedelta(days=report.retention_days - 1)
        start = earliest
        if should_use_incremental_field:
            cursor = as_report_date(db_incremental_field_last_value)
            if cursor is not None:
                start = max(cursor, earliest)

        pending = (
            resumable_source_manager.load_state()
            if resumable_source_manager is not None and resumable_source_manager.can_resume()
            else None
        )

        for window in report_windows(start, today, report.max_window_days):
            for profile_id in profile_ids:
                if (
                    pending is not None
                    and pending.profile_id == profile_id
                    and pending.window_start == window.start.isoformat()
                ):
                    report_id = pending.report_id
                    pending = None
                else:
                    created = request(
                        "POST",
                        config.path,
                        profile_id=profile_id,
                        body=report_request_body(report, window.start, window.end),
                        extra_headers={"Content-Type": REPORT_MEDIA_TYPE},
                    ).json()
                    report_id = created["reportId"]

                if resumable_source_manager is not None:
                    # Persist before the first poll — a retry that created a second report would
                    # be answered with a 425 until this one finished anyway.
                    resumable_source_manager.save_state(
                        AmazonAdsResumeConfig(
                            profile_id=profile_id,
                            window_start=window.start.isoformat(),
                            report_id=report_id,
                        )
                    )

                url = await_report_url(report, profile_id, report_id)
                if not url:
                    continue

                rows = download_report_rows(url, client_id, client_secret, refresh_token)
                # Amazon does not order the file, and the pipeline advances the `date` cursor from
                # each batch it writes, so a batch must never carry a date later than the rows
                # still to come for this profile.
                rows.sort(key=lambda row: str(row.get("date") or ""))
                for offset in range(0, len(rows), REPORT_ROWS_PER_BATCH):
                    yield [{**row, "_profile_id": profile_id} for row in rows[offset : offset + REPORT_ROWS_PER_BATCH]]

        if resumable_source_manager is not None:
            resumable_source_manager.clear_state()

    if endpoint == "profiles":
        profiles = list_profiles()
        if profiles:
            yield profiles
        return

    profile_ids = [str(profile["profileId"]) for profile in list_profiles()]

    if config.report is not None:
        yield from report_rows(config.report, profile_ids)
        return

    # Sponsored Products v3 list endpoints, fanned out per profile.
    for profile_id in profile_ids:
        next_token: Optional[str] = None
        while True:
            body: dict[str, Any] = {"maxResults": PAGE_SIZE}
            if next_token:
                body["nextToken"] = next_token
            data = request("POST", config.path, profile_id=profile_id, body=body).json()
            items = [{**item, "_profile_id": profile_id} for item in (data.get(config.data_key, []) or [])]

            if items:
                yield items

            next_token = data.get("nextToken")
            if not next_token or not items:
                break


def amazon_ads_source(
    region: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: Optional[ResumableSourceManager[AmazonAdsResumeConfig]] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = AMAZON_ADS_ENDPOINTS[endpoint]
    is_report = config.report is not None

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            region=region,
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=list(config.primary_keys),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if is_report else None,
        partition_format="day" if is_report else None,
        partition_keys=["date"] if is_report else None,
        sort_mode="asc",
    )
