import json
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account
from requests import Session

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    DEFAULT_RETRY,
    TrackedHTTPAdapter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_monitoring.settings import (
    BASE_URL,
    INITIAL_BACKFILL_DAYS,
    METRIC_DESCRIPTORS,
    MONITORED_RESOURCE_DESCRIPTORS,
    PAGE_SIZE,
    SCOPES,
    TIME_SERIES,
    WINDOW_HOURS,
)

# The point value arrives under exactly one of these keys, named for its value type.
VALUE_KEYS = ("doubleValue", "int64Value", "boolValue", "stringValue", "distributionValue")

# Always mint tokens against Google's fixed endpoint. Never POST to the uploaded key's
# `token_uri`: a source-write user could point it at an internal host (SSRF).
TOKEN_URI = "https://oauth2.googleapis.com/token"


@frozen
class GcpCloudMonitoringResumeConfig:
    next_start_time: str


@frozen
class TimeWindow:
    """A half-open query interval. Both bounds are datetimes, so naming them stops a window
    being queried end-first."""

    start: datetime
    end: datetime


class GcpCloudMonitoringError(Exception):
    pass


def make_authed_session(
    project_id: str,
    private_key: str,
    private_key_id: str,
    client_email: str,
) -> Session:
    """A session that injects the service account's bearer token and rides the tracked adapter."""
    credentials = service_account.Credentials.from_service_account_info(
        {
            "project_id": project_id,
            "private_key": private_key,
            "private_key_id": private_key_id,
            "client_email": client_email,
            "token_uri": TOKEN_URI,
        },
        scopes=SCOPES,
    )
    session = AuthorizedSession(credentials)
    tracked_adapter = TrackedHTTPAdapter(max_retries=DEFAULT_RETRY)
    session.mount("https://", tracked_adapter)
    session.mount("http://", tracked_adapter)
    return session


class GcpCloudMonitoringClient:
    def __init__(self, session: Session, project_id: str) -> None:
        self._session = session
        self._project_id = project_id

    def _paginate(self, path: str, params: dict[str, Any], collection: str) -> Iterator[list[dict[str, Any]]]:
        page_token: Optional[str] = None
        while True:
            page_params = dict(params)
            if page_token:
                page_params["pageToken"] = page_token
            response = self._session.get(f"{BASE_URL}/projects/{self._project_id}/{path}", params=page_params)
            response.raise_for_status()
            payload = response.json()

            items = payload.get(collection) or []
            if items:
                yield items

            page_token = payload.get("nextPageToken")
            # Cloud Monitoring signals the end with an absent or empty token.
            if not page_token:
                return

    def list_metric_descriptors(self) -> Iterator[list[dict[str, Any]]]:
        yield from self._paginate("metricDescriptors", {"pageSize": PAGE_SIZE}, "metricDescriptors")

    def list_monitored_resource_descriptors(self) -> Iterator[list[dict[str, Any]]]:
        yield from self._paginate("monitoredResourceDescriptors", {"pageSize": PAGE_SIZE}, "resourceDescriptors")

    def list_time_series(self, params: dict[str, Any]) -> Iterator[list[dict[str, Any]]]:
        yield from self._paginate("timeSeries", params, "timeSeries")


def _as_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _time_windows(start: datetime, end: datetime, window_hours: int) -> Iterator[TimeWindow]:
    cursor = start
    while cursor < end:
        window_end = min(cursor + timedelta(hours=window_hours), end)
        yield TimeWindow(start=cursor, end=window_end)
        cursor = window_end


def resolve_start_time(db_incremental_field_last_value: Any, now: datetime) -> datetime:
    cursor = _as_datetime(db_incremental_field_last_value)
    if cursor is None:
        return now - timedelta(days=INITIAL_BACKFILL_DAYS)
    return cursor


def series_key(metric: dict[str, Any], resource: dict[str, Any]) -> str:
    """Stable identity for one time series: its metric type plus every label that splits it.

    Cloud Monitoring gives a series no id of its own, so the key is derived. Labels are sorted
    before hashing, because the API does not promise a stable key order between responses.
    """
    identity = {
        "metric_type": metric.get("type"),
        "metric_labels": metric.get("labels") or {},
        "resource_type": resource.get("type"),
        "resource_labels": resource.get("labels") or {},
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def flatten_time_series(time_series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per point. A series carries its labels onto every point it produced."""
    rows: list[dict[str, Any]] = []
    for series in time_series:
        metric = series.get("metric") or {}
        resource = series.get("resource") or {}
        key = series_key(metric, resource)

        for point in series.get("points") or []:
            interval = point.get("interval") or {}
            value = point.get("value") or {}
            row: dict[str, Any] = {
                "series_key": key,
                "metric_type": metric.get("type"),
                "metric_labels": metric.get("labels") or {},
                "resource_type": resource.get("type"),
                "resource_labels": resource.get("labels") or {},
                "metric_kind": series.get("metricKind"),
                "value_type": series.get("valueType"),
                "point_start_time": interval.get("startTime"),
                "point_end_time": interval.get("endTime"),
            }
            for value_key in VALUE_KEYS:
                row[value_key] = value.get(value_key)
            rows.append(row)
    return rows


def aggregation_config_error(
    alignment_period_seconds: Optional[int],
    per_series_aligner: Optional[str],
    cross_series_reducer: Optional[str],
    group_by_fields: Optional[list[str]],
) -> Optional[str]:
    """The API ignores a reducer, group-by or period that has nothing to hang off, so a setting
    that would be dropped is refused instead of importing raw data the user didn't ask for."""
    if not per_series_aligner:
        dropped = [
            label
            for label, value in (
                ("a cross-series reducer", cross_series_reducer),
                ("group-by fields", group_by_fields),
                ("an alignment period", alignment_period_seconds),
            )
            if value
        ]
        if dropped:
            return f"Setting {' and '.join(dropped)} needs a per-series aligner, for example ALIGN_SUM."
    if group_by_fields and not cross_series_reducer:
        return "Group-by fields need a cross-series reducer, for example REDUCE_SUM."
    return None


def build_time_series_params(
    metric_filter: str,
    window_start: datetime,
    window_end: datetime,
    alignment_period_seconds: Optional[int],
    per_series_aligner: Optional[str],
    cross_series_reducer: Optional[str],
    group_by_fields: Optional[list[str]],
) -> dict[str, Any]:
    """Request one window of points.

    Aggregation stays off unless the user asks for it. A valid aligner depends on the metric's
    kind and value type, so a default one would reject some of the filters a user can write.
    """
    error = aggregation_config_error(
        alignment_period_seconds, per_series_aligner, cross_series_reducer, group_by_fields
    )
    if error:
        raise GcpCloudMonitoringError(error)

    params: dict[str, Any] = {
        "filter": metric_filter,
        "interval.startTime": _rfc3339(window_start),
        "interval.endTime": _rfc3339(window_end),
        "view": "FULL",
        "pageSize": PAGE_SIZE,
    }

    if per_series_aligner:
        params["aggregation.perSeriesAligner"] = per_series_aligner
        # The API rejects an aligner other than ALIGN_NONE without a period to align to.
        params["aggregation.alignmentPeriod"] = f"{alignment_period_seconds or 3600}s"
        if cross_series_reducer:
            params["aggregation.crossSeriesReducer"] = cross_series_reducer
            if group_by_fields:
                # requests repeats the key once per element, which is how the API takes a list.
                params["aggregation.groupByFields"] = list(group_by_fields)

    return params


def gcp_cloud_monitoring_source(
    client: GcpCloudMonitoringClient,
    endpoint_name: str,
    resumable_source_manager: ResumableSourceManager[GcpCloudMonitoringResumeConfig],
    metric_filter: str,
    db_incremental_field_last_value: Any = None,
    alignment_period_seconds: Optional[int] = None,
    per_series_aligner: Optional[str] = None,
    cross_series_reducer: Optional[str] = None,
    group_by_fields: Optional[list[str]] = None,
    now: Optional[datetime] = None,
) -> Iterator[list[dict[str, Any]]]:
    if endpoint_name == METRIC_DESCRIPTORS:
        yield from client.list_metric_descriptors()
        return

    if endpoint_name == MONITORED_RESOURCE_DESCRIPTORS:
        yield from client.list_monitored_resource_descriptors()
        return

    if endpoint_name != TIME_SERIES:
        raise GcpCloudMonitoringError(f"Unknown Cloud Monitoring table {endpoint_name}")

    if not metric_filter:
        raise GcpCloudMonitoringError(
            "The TimeSeries table needs a monitoring filter. Set one on the source, for example "
            'resource.type="consumed_api" AND metric.type="serviceruntime.googleapis.com/api/request_count".'
        )

    end_time = now or datetime.now(tz=UTC)
    start_time = resolve_start_time(db_incremental_field_last_value, end_time)

    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            resumed = _as_datetime(resume_config.next_start_time)
            if resumed is not None:
                start_time = resumed

    for window in _time_windows(start_time, end_time, WINDOW_HOURS):
        params = build_time_series_params(
            metric_filter,
            window.start,
            window.end,
            alignment_period_seconds,
            per_series_aligner,
            cross_series_reducer,
            group_by_fields,
        )

        window_rows: list[dict[str, Any]] = []
        for page in client.list_time_series(params):
            window_rows.extend(flatten_time_series(page))

        if window_rows:
            # A series returns its points newest first, and pages interleave series, so the
            # window is sorted here rather than trusting the response order. `sort_mode="asc"`
            # on the source depends on this.
            window_rows.sort(key=lambda row: row["point_end_time"] or "")
            yield window_rows

        # Saved after the yield: a crash re-reads this window and the merge dedupes on the
        # primary key, where saving first would skip it.
        resumable_source_manager.save_state(GcpCloudMonitoringResumeConfig(next_start_time=_rfc3339(window.end)))


def validate_credentials(session: Session, project_id: str) -> tuple[bool, str | None]:
    try:
        response = session.get(
            f"{BASE_URL}/projects/{project_id}/metricDescriptors",
            params={"pageSize": 1},
        )
    except Exception:
        return False, "Could not reach Cloud Monitoring with this service account key."

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return (
            False,
            f"The service account cannot read Cloud Monitoring in project {project_id}. "
            "Grant it the Monitoring Viewer role and try again.",
        )
    if response.status_code == 404:
        return False, f"Google Cloud project {project_id} was not found."
    return False, f"Cloud Monitoring returned {response.status_code} when validating the credentials."
