import re
from bisect import bisect_left
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from requests import ReadTimeout
from requests.auth import HTTPBasicAuth
from urllib3.util.retry import Retry

from products.warehouse_sources.sources.sdk import (
    HttpBasicAuth,
    OffsetPaginator,
    RESTClient,
    RESTClientRetryableError,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    frozen,
    make_tracked_session,
)
from products.warehouse_sources.sources.unity_ads.settings import (
    HISTORY_DAYS,
    MANAGEMENT_PRIMARY_KEYS,
    UNITY_ADS_ENDPOINTS,
    UNITY_MANAGEMENT_URL,
    UNITY_STATS_URL,
    UnityAdsEndpointConfig,
)

# Unity allows a report request 10 minutes, but one request may hold a worker for 5 at most, so short
# windows keep each response well inside this read timeout. The retry budget matches it, so a window
# that times out is halved after one attempt instead of being sent again at full size.
REQUEST_TIMEOUT = (10, 240)
# Setup waits on the probe, so it gets one attempt. Even a one-day report takes Unity a while to build.
PROBE_TIMEOUT = 60

INVALID_ORGANIZATION_ID = "The Unity organization ID must be the numeric Organization core ID"
_MANAGEMENT_ID = re.compile(r"[0-9a-fA-F]{24}")
_APPS_PAGE_SIZE = 1000
STATS_PERMISSION_ERROR = "Give the service account the Advertise Stats API Viewer role."
MANAGEMENT_PERMISSION_ERROR = "Enable the Advertising Management API for your organization. Give the service account the Advertise API Viewer role."


@frozen
class UnityAdsResumeConfig:
    next_window_start: str | None = None
    # The window size after halving, so a resumed run does not time out again on full-size windows.
    window_days: int | None = None
    apps_offset: int = 0
    next_app_id: str | None = None
    next_campaign_id: str | None = None


def to_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _iso(day: date) -> str:
    return f"{day.isoformat()}T00:00:00Z"


def _windows(
    client: RESTClient,
    url: str,
    config: UnityAdsEndpointConfig,
    window_days: int,
    start: date,
    today: date,
    manager: ResumableSourceManager[UnityAdsResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    window = start
    span = window_days
    while window <= today:
        last_day = min(window + timedelta(days=span - 1), today)
        rows: list[dict[str, Any]] = []
        try:
            # A 204 for a window with no data parses as an empty page.
            for page in client.paginate(
                url,
                params={
                    "start": _iso(window),
                    # `end` is exclusive.
                    "end": _iso(last_day + timedelta(days=1)),
                    "scale": "day",
                    "metrics": ",".join(config.metrics),
                    "breakdowns": ",".join(config.breakdowns),
                    "format": "json",
                },
                paginator=SinglePagePaginator(),
                data_selector="data",
            ):
                rows.extend(page)
        except RESTClientRetryableError as error:
            # A report too large for the read timeout fails the same way on every retry, so ask for
            # half the days instead. A single day that still times out fails the run.
            if not isinstance(error.__cause__, ReadTimeout) or last_day == window:
                raise
            span = max(1, ((last_day - window).days + 1) // 2)
            manager.save_state(UnityAdsResumeConfig(next_window_start=window.isoformat(), window_days=span))
            manager.safe_point()
            continue

        next_window = last_day + timedelta(days=1)
        if next_window <= today:
            manager.save_state(UnityAdsResumeConfig(next_window_start=next_window.isoformat(), window_days=span))
        if rows:
            # Rows arrive in no stated order, and the source declares ascending order to the pipeline.
            rows.sort(key=lambda row: str(row.get("timestamp") or ""))
            yield rows
        else:
            manager.safe_point()
        window = next_window


def _management_id(row: dict[str, Any]) -> str:
    identifier = row.get("id")
    if not isinstance(identifier, str) or not _MANAGEMENT_ID.fullmatch(identifier):
        raise ValueError("Unity returned an invalid app or campaign ID")
    return identifier


def _resume_index(ids: list[str], next_id: str | None) -> int:
    return bisect_left(ids, next_id) if next_id is not None else 0


def _management_page(client: RESTClient, url: str) -> list[dict[str, Any]]:
    return next(client.paginate(url, paginator=SinglePagePaginator(), data_selector="results"), [])


def _management_app_rows(
    client: RESTClient,
    apps_url: str,
    endpoint: str,
    manager: ResumableSourceManager[UnityAdsResumeConfig],
    current_app: UnityAdsResumeConfig,
    next_app: UnityAdsResumeConfig,
) -> Iterator[list[dict[str, Any]]]:
    app_id = current_app.next_app_id
    campaigns_url = f"{apps_url}/{app_id}/campaigns"
    campaigns = _management_page(client, campaigns_url)
    if not campaigns or endpoint == "campaigns":
        manager.save_state(next_app)
        if campaigns:
            yield [{**campaign, "campaignSetId": app_id} for campaign in campaigns]
        else:
            manager.safe_point()
        return

    bid_path = endpoint.replace("_", "-")
    campaign_ids = sorted(_management_id(campaign) for campaign in campaigns)
    first_campaign = _resume_index(campaign_ids, current_app.next_campaign_id)
    if first_campaign == len(campaign_ids):
        manager.save_state(next_app)
        manager.safe_point()
        return
    for campaign_index in range(first_campaign, len(campaign_ids)):
        campaign_id = campaign_ids[campaign_index]
        bids = _management_page(client, f"{campaigns_url}/{campaign_id}/{bid_path}")
        manager.save_state(
            replace(current_app, next_campaign_id=campaign_ids[campaign_index + 1])
            if campaign_index + 1 < len(campaign_ids)
            else next_app
        )
        if bids:
            yield [{**bid, "campaignSetId": app_id, "campaignId": campaign_id} for bid in bids]
        else:
            manager.safe_point()


def _management_rows(
    client: RESTClient,
    url: str,
    endpoint: str,
    manager: ResumableSourceManager[UnityAdsResumeConfig],
    resume: UnityAdsResumeConfig,
) -> Iterator[list[dict[str, Any]]]:
    apps_url = f"{url}/apps"
    offset = resume.apps_offset
    for apps in client.paginate(
        apps_url, paginator=OffsetPaginator(limit=_APPS_PAGE_SIZE, offset=offset), data_selector="results"
    ):
        next_page = UnityAdsResumeConfig(apps_offset=offset + _APPS_PAGE_SIZE)
        if not apps:
            manager.safe_point()
            return
        if endpoint == "apps":
            manager.save_state(next_page)
            yield apps
        else:
            app_ids = sorted(_management_id(app) for app in apps)
            next_app_id = resume.next_app_id if offset == resume.apps_offset else None
            first_app = _resume_index(app_ids, next_app_id)
            if first_app == len(app_ids):
                manager.save_state(next_page)
                manager.safe_point()
            for app_index in range(first_app, len(app_ids)):
                app_id = app_ids[app_index]
                next_app = (
                    UnityAdsResumeConfig(apps_offset=offset, next_app_id=app_ids[app_index + 1])
                    if app_index + 1 < len(app_ids)
                    else next_page
                )
                current_app = UnityAdsResumeConfig(
                    apps_offset=offset,
                    next_app_id=app_id,
                    next_campaign_id=resume.next_campaign_id if app_id == next_app_id else None,
                )
                yield from _management_app_rows(client, apps_url, endpoint, manager, current_app, next_app)
        offset = next_page.apps_offset


def unity_ads_source(
    organization_id: str,
    key_id: str,
    secret_key: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[UnityAdsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    organization_id = organization_id.strip()
    # The ID goes into the request path, so anything but digits is refused.
    if not organization_id.isdigit():
        raise ValueError(INVALID_ORGANIZATION_ID)
    client = RESTClient(
        auth=HttpBasicAuth(key_id, secret_key),
        request_timeout=REQUEST_TIMEOUT,
        retry_budget_seconds=REQUEST_TIMEOUT[1],
    )
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if endpoint in MANAGEMENT_PRIMARY_KEYS:
        management_url = UNITY_MANAGEMENT_URL.format(organization_id=organization_id)
        return SourceResponse(
            name=endpoint,
            items=lambda: _management_rows(
                client, management_url, endpoint, resumable_source_manager, resume or UnityAdsResumeConfig()
            ),
            primary_keys=list(MANAGEMENT_PRIMARY_KEYS[endpoint]),
        )

    config = UNITY_ADS_ENDPOINTS[endpoint]
    today = datetime.now(UTC).date()
    floor = today - timedelta(days=HISTORY_DAYS)

    window_days = config.window_days
    if resume is not None and resume.next_window_start is not None:
        window_days = min(resume.window_days or window_days, window_days)
        start = date.fromisoformat(resume.next_window_start)
    elif should_use_incremental_field and db_incremental_field_last_value is not None:
        start = max(to_date(db_incremental_field_last_value), floor)
    else:
        start = floor

    url = UNITY_STATS_URL.format(organization_id=organization_id, report=config.report)

    return SourceResponse(
        name=endpoint,
        items=lambda: _windows(client, url, config, window_days, start, today, resumable_source_manager),
        primary_keys=list(config.primary_keys),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=["timestamp"],
        sort_mode="asc",
    )


def _stats_probe_params(report: UnityAdsEndpointConfig | None) -> dict[str, str | int]:
    today = datetime.now(UTC).date()
    params: dict[str, str | int] = {
        "start": _iso(today - timedelta(days=1)),
        "end": _iso(today),
        "scale": "day",
        "metrics": ",".join(report.metrics) if report else "starts",
        "format": "json",
    }
    if report is not None:
        params["breakdowns"] = ",".join(report.breakdowns)
    return params


def validate_credentials(
    organization_id: str, key_id: str, secret_key: str, schema_name: str | None = None
) -> tuple[bool, str | None]:
    organization_id = organization_id.strip()
    if not organization_id.isdigit():
        return False, f"{INVALID_ORGANIZATION_ID}. Find it under Settings in the Unity Ads dashboard."
    management = schema_name in MANAGEMENT_PRIMARY_KEYS
    apps_url = f"{UNITY_MANAGEMENT_URL.format(organization_id=organization_id)}/apps"
    if management:
        url = apps_url
        params: dict[str, str | int] = {"limit": 1}
    else:
        report = UNITY_ADS_ENDPOINTS.get(schema_name) if schema_name is not None else None
        url = UNITY_STATS_URL.format(
            organization_id=organization_id, report=report.report if report else "acquisitions"
        )
        params = _stats_probe_params(report)

    try:
        with make_tracked_session(redact_values=(secret_key,), allow_redirects=False, retry=Retry(total=0)) as session:
            auth = HTTPBasicAuth(key_id, secret_key)
            response = session.get(url, params=params, auth=auth, timeout=PROBE_TIMEOUT)
            if schema_name is None and response.status_code == 403:
                response = session.get(apps_url, params={"limit": 1}, auth=auth, timeout=PROBE_TIMEOUT)
    except Exception:  # noqa: BLE001 — a credential probe must never raise; any failure means "not validated"
        return False, "Could not connect to Unity. Try again in a minute."
    if response.status_code in (200, 204):
        return True, None
    if response.status_code == 401:
        return False, "Unity rejected the key ID or secret key. Check the service account key and try again."
    if response.status_code == 403:
        if schema_name is None:
            return False, (
                "Give the service account the Advertise Stats API Viewer role or the Advertise API Viewer role."
            )
        return False, MANAGEMENT_PERMISSION_ERROR if management else STATS_PERMISSION_ERROR
    if response.status_code == 404:
        return False, "Unity found no organization with that ID. Use the Organization core ID from Settings."
    return False, "Could not connect to Unity. Try again in a minute."
