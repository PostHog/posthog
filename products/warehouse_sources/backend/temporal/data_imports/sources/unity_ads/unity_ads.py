from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from requests import ReadTimeout
from requests.auth import HTTPBasicAuth
from urllib3.util.retry import Retry

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClient,
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.unity_ads.settings import (
    HISTORY_DAYS,
    METRICS,
    UNITY_ADS_ENDPOINTS,
    UNITY_STATS_URL,
)

# Unity allows a report request 10 minutes, but one request may hold a worker for 5 at most, so short
# windows keep each response well inside this read timeout. The retry budget matches it, so a window
# that times out is halved after one attempt instead of being sent again at full size.
REQUEST_TIMEOUT = (10, 240)
# Setup waits on the probe, so it gets one attempt. Even a one-day report takes Unity a while to build.
PROBE_TIMEOUT = 60

INVALID_ORGANIZATION_ID = "The Unity organization ID must be the numeric Organization core ID"


@frozen
class UnityAdsResumeConfig:
    next_window_start: str
    # The window size after halving, so a resumed run does not time out again on full-size windows.
    window_days: int | None = None


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
    breakdowns: tuple[str, ...],
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
                    "metrics": ",".join(METRICS),
                    "breakdowns": ",".join(breakdowns),
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


def unity_ads_source(
    organization_id: str,
    key_id: str,
    secret_key: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[UnityAdsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = UNITY_ADS_ENDPOINTS[endpoint]
    organization_id = organization_id.strip()
    # The ID goes into the request path, so anything but digits is refused.
    if not organization_id.isdigit():
        raise ValueError(INVALID_ORGANIZATION_ID)
    today = datetime.now(UTC).date()
    floor = today - timedelta(days=HISTORY_DAYS)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    window_days = config.window_days
    if resume is not None:
        window_days = min(resume.window_days or window_days, window_days)
        start = date.fromisoformat(resume.next_window_start)
    elif should_use_incremental_field and db_incremental_field_last_value is not None:
        start = max(to_date(db_incremental_field_last_value), floor)
    else:
        start = floor

    client = RESTClient(
        auth=HttpBasicAuth(key_id, secret_key),
        request_timeout=REQUEST_TIMEOUT,
        retry_budget_seconds=REQUEST_TIMEOUT[1],
    )
    url = UNITY_STATS_URL.format(organization_id=organization_id)

    return SourceResponse(
        name=endpoint,
        items=lambda: _windows(client, url, config.breakdowns, window_days, start, today, resumable_source_manager),
        primary_keys=list(config.primary_keys),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=["timestamp"],
        sort_mode="asc",
    )


def validate_credentials(organization_id: str, key_id: str, secret_key: str) -> tuple[bool, str | None]:
    if not organization_id.strip().isdigit():
        return False, f"{INVALID_ORGANIZATION_ID}. Find it under Settings in the Unity Ads dashboard."
    today = datetime.now(UTC).date()
    try:
        response = make_tracked_session(redact_values=(secret_key,), allow_redirects=False, retry=Retry(total=0)).get(
            UNITY_STATS_URL.format(organization_id=organization_id.strip()),
            params={
                "start": _iso(today - timedelta(days=1)),
                "end": _iso(today),
                "scale": "day",
                "metrics": "starts",
                "format": "json",
            },
            auth=HTTPBasicAuth(key_id, secret_key),
            timeout=PROBE_TIMEOUT,
        )
    except Exception:  # noqa: BLE001 — a credential probe must never raise; any failure means "not validated"
        return False, "Could not connect to Unity. Try again in a minute."
    if response.status_code in (200, 204):
        return True, None
    if response.status_code == 401:
        return False, "Unity rejected the key ID or secret key. Check the service account key and try again."
    if response.status_code == 403:
        return (
            False,
            "The service account cannot read statistics for this organization. Give it the Advertise Stats API Viewer role.",
        )
    if response.status_code == 404:
        return False, "Unity found no organization with that ID. Use the Organization core ID from Settings."
    return False, "Could not connect to Unity. Try again in a minute."
