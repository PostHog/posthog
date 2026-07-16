from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

APPLICATIONS_PATH = "/controller/rest/applications"

# Metric paths synced when the user leaves the "Metric paths" field empty. App-level KPIs
# (calls per minute, average response time, error rate, ...) broken out per tier.
DEFAULT_METRIC_PATHS = ["Overall Application Performance|*"]

# The metric_data stream sends one request per (application, metric path, time window), so an
# unbounded path list would let a single source config fan out into tens of thousands of
# requests per sync and monopolize shared import workers. Wildcards make broad coverage
# possible well within this cap.
MAX_METRIC_PATHS = 50

# The Controller's time-windowed endpoints filter server-side on epoch-ms `start-time` /
# `end-time` (`time-range-type=BETWEEN_TIMES`), so the row's `startTimeInMillis` is the
# only reliable incremental cursor. There is no `updated-since` filter on any endpoint.
TIME_WINDOW_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "startTimeInMillis",
        "type": IncrementalFieldType.Integer,
        "field": "startTimeInMillis",
        "field_type": IncrementalFieldType.Integer,
    },
]


@dataclass
class AppdynamicsEndpointConfig:
    name: str
    """Stream name shown to the user."""
    path: str
    """Controller REST path. Fan-out paths carry an `{application_id}` placeholder."""
    primary_keys: list[str]
    """Unique across the whole table — fan-out children include `application_id`."""
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    fan_out_over_applications: bool = False
    """Iterate every application and query this endpoint once per application."""
    time_windowed: bool = False
    """Endpoint requires `time-range-type=BETWEEN_TIMES` with epoch-ms start/end params."""
    is_metric_data: bool = False
    """Metric-data responses nest `metricValues` per metric; rows are flattened out of them."""
    default_lookback_days: int = 30
    """First-sync / full-refresh window for time-windowed endpoints."""
    window_chunk_days: int = 7
    """Time-windowed fetches are chunked so responses stay bounded and resumable."""
    description: str | None = None


APPDYNAMICS_ENDPOINTS: dict[str, AppdynamicsEndpointConfig] = {
    "applications": AppdynamicsEndpointConfig(
        name="applications",
        path=APPLICATIONS_PATH,
        primary_keys=["id"],
    ),
    "business_transactions": AppdynamicsEndpointConfig(
        name="business_transactions",
        path="/controller/rest/applications/{application_id}/business-transactions",
        primary_keys=["application_id", "id"],
        fan_out_over_applications=True,
    ),
    "tiers": AppdynamicsEndpointConfig(
        name="tiers",
        path="/controller/rest/applications/{application_id}/tiers",
        primary_keys=["application_id", "id"],
        fan_out_over_applications=True,
    ),
    "nodes": AppdynamicsEndpointConfig(
        name="nodes",
        path="/controller/rest/applications/{application_id}/nodes",
        primary_keys=["application_id", "id"],
        fan_out_over_applications=True,
    ),
    "health_rule_violations": AppdynamicsEndpointConfig(
        name="health_rule_violations",
        path="/controller/rest/applications/{application_id}/problems/healthrule-violations",
        primary_keys=["application_id", "id"],
        fan_out_over_applications=True,
        time_windowed=True,
        incremental_fields=TIME_WINDOW_INCREMENTAL_FIELDS,
        default_lookback_days=30,
        window_chunk_days=7,
        description=(
            "Health rule violations are synced by their start time. Status changes to previously "
            "synced violations (e.g. a violation resolving) are only picked up on a full refresh. "
            "Only syncs the last 30 days on initial sync."
        ),
    ),
    "metric_data": AppdynamicsEndpointConfig(
        name="metric_data",
        path="/controller/rest/applications/{application_id}/metric-data",
        primary_keys=["application_id", "metricId", "startTimeInMillis"],
        fan_out_over_applications=True,
        time_windowed=True,
        is_metric_data=True,
        incremental_fields=TIME_WINDOW_INCREMENTAL_FIELDS,
        default_lookback_days=7,
        window_chunk_days=1,
        description=(
            "Metric time series for the metric paths configured on the source (defaults to "
            "'Overall Application Performance|*'). One row per metric per interval. "
            "Only syncs the last 7 days on initial sync."
        ),
    ),
}

ENDPOINTS = tuple(APPDYNAMICS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in APPDYNAMICS_ENDPOINTS.items()
}
