from dataclasses import field
from typing import Any

from posthog.dataclasses import frozen

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

# Application-fan-out streams issue at least one request per application, multiplied by time
# windows and metric paths. The application list comes from the user-supplied controller, so
# an unbounded catalog would let a hostile or misconfigured host monopolize a shared import
# worker. Cap the catalog size per sync (generous enough for real accounts).
MAX_APPLICATIONS = 1000

# The per-dimension caps still multiply — applications × metric paths × time windows — so bound
# the Cartesian product too. A sync above this many estimated requests is rejected before the
# fan-out starts, keeping a large-but-legal catalog from holding a worker for the activity's
# week-long timeout. Generous enough for realistic accounts; the worst pathological combination
# (max applications × max metric paths × the 7-day metric window) lands well above it.
MAX_FANOUT_REQUESTS = 100_000

# The Controller caps `events` and `request-snapshots` responses at 600 rows and offers no
# cursor to page past that, so a window that comes back full is assumed truncated and gets
# bisected until each half fits (see `_get_window_rows`).
MAX_ROWS_PER_TIME_WINDOW = 600

# Bounds on that bisection: stop splitting once a window is under a minute (a minute that
# still overflows 600 rows cannot be recovered by splitting further), and cap the extra
# requests one top-level window may cost so a firehose application can't monopolize a worker.
MIN_WINDOW_SPLIT_MS = 60 * 1000
MAX_WINDOW_SPLITS = 64

# Event types synced when the user leaves the "Event types" field empty: deployments,
# restarts, config changes, application errors, diagnostic sessions and the health rule
# violation state transitions. `event-types` is a required parameter with no "all" value,
# and the Controller rejects the whole request if any type is unknown, so the default
# stays on long-standing types and users add the rest themselves.
DEFAULT_EVENT_TYPES = [
    "APPLICATION_DEPLOYMENT",
    "APP_SERVER_RESTART",
    "APPLICATION_CONFIG_CHANGE",
    "APPLICATION_ERROR",
    "DIAGNOSTIC_SESSION",
    "CUSTOM",
    "POLICY_OPEN_WARNING",
    "POLICY_OPEN_CRITICAL",
    "POLICY_UPGRADED",
    "POLICY_DOWNGRADED",
    "POLICY_CLOSE_WARNING",
    "POLICY_CLOSE_CRITICAL",
]

# `event-types` rides in the query string, so an unbounded list would also build an
# unbounded URL. Well past the number of event types the Controller defines.
MAX_EVENT_TYPES = 200

# `severities` is required too, and every severity is wanted for an event history.
EVENT_SEVERITIES = "INFO,WARN,ERROR"

# `anomalies` pages with `pageSize`/`pageNumber` and documents no default page size, so the
# stream always sends one and walks pages until one comes back short — relying on an omitted
# param to return everything would silently drop rows if the Controller applies its own default.
ANOMALIES_PAGE_SIZE = 500

# Pages one time window may fetch before the stream gives up on it, so a window holding an
# unexpectedly large number of anomalies cannot loop a worker indefinitely.
MAX_PAGES_PER_TIME_WINDOW = 64

# `/metrics` returns only the immediate children of a path, so browsing the tree costs one
# request per folder. The hierarchy is unbounded (a folder per tier, node and business
# transaction), so bound both how deep the walk goes and what it may spend per application.
METRIC_TREE_MAX_DEPTH = 3
METRIC_TREE_MAX_REQUESTS_PER_APPLICATION = 100


# The Controller's time-windowed endpoints filter server-side on epoch-ms `start-time` /
# `end-time` (`time-range-type=BETWEEN_TIMES`), so each endpoint's own epoch-ms start field
# is the only reliable incremental cursor. There is no `updated-since` filter on any endpoint.
def time_window_incremental_fields(field_name: str) -> list[IncrementalField]:
    return [
        {
            "label": field_name,
            "type": IncrementalFieldType.Integer,
            "field": field_name,
            "field_type": IncrementalFieldType.Integer,
        },
    ]


TIME_WINDOW_INCREMENTAL_FIELDS: list[IncrementalField] = time_window_incremental_fields("startTimeInMillis")


@frozen
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
    is_events: bool = False
    """Events requests carry the required `event-types` list configured on the source."""
    is_metric_tree: bool = False
    """Walk the metric hierarchy folder by folder instead of reading one list response."""
    uses_epoch_time_params: bool = False
    """Window bounds ride as bare epoch-ms `startTime`/`endTime` instead of the `time-range-type` triple."""
    data_selector: str | None = None
    """Key holding the row list, for endpoints that wrap it in an object instead of returning an array."""
    page_size: int | None = None
    """Page rows with `pageSize`/`pageNumber` instead of reading a whole window in one response."""
    result_cap: int | None = None
    """Rows the endpoint returns per request at most. A window at the cap is bisected."""
    extra_params: dict[str, Any] = field(default_factory=dict)
    """Static query params this endpoint always sends."""
    sends_output_json_param: bool = True
    """Controller REST defaults to XML; the alerting API serves JSON and has no such param."""
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
    "backends": AppdynamicsEndpointConfig(
        name="backends",
        path="/controller/rest/applications/{application_id}/backends",
        primary_keys=["application_id", "id"],
        fan_out_over_applications=True,
        description=(
            "Backends (remote services, databases and message queues) that each application's "
            "tiers and business transactions call."
        ),
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
    "anomalies": AppdynamicsEndpointConfig(
        name="anomalies",
        path="/controller/anomaly/rest/api/v1/applications/{application_id}/anomalies",
        primary_keys=["application_id", "id"],
        fan_out_over_applications=True,
        time_windowed=True,
        uses_epoch_time_params=True,
        sends_output_json_param=False,
        data_selector="violationListItem",
        page_size=ANOMALIES_PAGE_SIZE,
        incremental_fields=time_window_incremental_fields("startTime"),
        extra_params={"fetchSuspectedCause": "false"},
        default_lookback_days=30,
        window_chunk_days=7,
        description=(
            "Anomaly detection violations, the machine-learning counterpart to health rule "
            "violations, synced by their start time. Suspected causes are not synced. Status "
            "changes to previously synced anomalies are only picked up on a full refresh. "
            "Only syncs the last 30 days on initial sync. Requires anomaly detection to be "
            "enabled on the controller."
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
    "events": AppdynamicsEndpointConfig(
        name="events",
        path="/controller/rest/applications/{application_id}/events",
        primary_keys=["application_id", "id"],
        fan_out_over_applications=True,
        time_windowed=True,
        is_events=True,
        incremental_fields=time_window_incremental_fields("eventTime"),
        default_lookback_days=30,
        window_chunk_days=1,
        result_cap=MAX_ROWS_PER_TIME_WINDOW,
        extra_params={"severities": EVENT_SEVERITIES},
        description=(
            "Application events (deployments, restarts, config changes, errors, diagnostic "
            "sessions and health rule violation state changes) synced by their event time. "
            "Syncs the event types configured on the source. Only syncs the last 30 days on "
            "initial sync."
        ),
    ),
    "request_snapshots": AppdynamicsEndpointConfig(
        name="request_snapshots",
        path="/controller/rest/applications/{application_id}/request-snapshots",
        primary_keys=["application_id", "id"],
        fan_out_over_applications=True,
        time_windowed=True,
        incremental_fields=time_window_incremental_fields("serverStartTime"),
        default_lookback_days=3,
        window_chunk_days=1,
        result_cap=MAX_ROWS_PER_TIME_WINDOW,
        extra_params={"maximum-results": MAX_ROWS_PER_TIME_WINDOW},
        description=(
            "Transaction snapshots for slow, stalled and error requests, synced by the time "
            "the request started on the server. Only syncs the last 3 days on initial sync."
        ),
    ),
    "health_rules": AppdynamicsEndpointConfig(
        name="health_rules",
        path="/controller/alerting/rest/v1/applications/{application_id}/health-rules",
        primary_keys=["application_id", "id"],
        fan_out_over_applications=True,
        sends_output_json_param=False,
        description="Health rules defined for each application, resolving the rule names on health rule violations.",
    ),
    "metrics": AppdynamicsEndpointConfig(
        name="metrics",
        path="/controller/rest/applications/{application_id}/metrics",
        primary_keys=["application_id", "path"],
        fan_out_over_applications=True,
        is_metric_tree=True,
        description=(
            "Metric paths available in each application's metric browser, one row per folder "
            "or metric. Use a path from here in the source's metric paths setting to sync its "
            "time series into metric_data."
        ),
    ),
    "database_servers": AppdynamicsEndpointConfig(
        name="database_servers",
        path="/controller/rest/databases/servers",
        primary_keys=["id"],
        description=(
            "Database servers monitored by AppDynamics Database Visibility. Joins to the "
            "database backends that applications call."
        ),
    ),
}

ENDPOINTS = tuple(APPDYNAMICS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in APPDYNAMICS_ENDPOINTS.items()
}
