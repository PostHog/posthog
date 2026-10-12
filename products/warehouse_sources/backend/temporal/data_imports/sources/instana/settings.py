from dataclasses import field
from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Instana's paginated application-monitoring catalogs accept a `pageSize` param; their analyze
# endpoints cap page sizes at 200, so stay at that known-safe value here too.
PAGE_SIZE = 200

# A self-hosted server the user controls can return a full page on every request while never
# signalling the end of pagination, keeping the catalog walk (and its ingestion) running for the
# whole activity. Two independent bounds stop the walk and fail non-retryably:
#
#  - A cumulative wall-clock budget is the effective bound. A page count alone doesn't cap worker
#    time — each page may stream for MAX_DOWNLOAD_SECONDS, so a slow host could stay under a page
#    cap yet hold the worker for days. 30 minutes is far longer than any real catalog walk (which
#    is minutes) but far below the import activity timeout, so a slow-drip host is evicted quickly.
#  - A page ceiling is a secondary record/memory bound (10k pages x 200 = 2M records), far above
#    any real catalog, so a legitimate inventory is never truncated.
MAX_CATALOG_WALK_SECONDS = 30 * 60
MAX_CATALOG_PAGES = 10_000

# `/api/events` has no pagination — the window itself bounds the response — so wide ranges must be
# chunked. One-day chunks keep responses small while the first sync stays at ~30 requests.
EVENTS_WINDOW_CHUNK_MS = 24 * 60 * 60 * 1000

# First sync / full refresh reaches back this far. Instana retains events for a limited window
# (typically ~31 days), so asking for more returns nothing extra.
EVENTS_DEFAULT_LOOKBACK_DAYS = 30

# `/api/infrastructure-monitoring/snapshots` has a `size` cap instead of pagination. The window
# only needs to cover entities currently reporting, so keep it short.
SNAPSHOTS_WINDOW_MS = 60 * 60 * 1000
SNAPSHOTS_MAX_SIZE = 1000

# The application-monitoring metrics APIs are POST-with-body time-series queries. They are synced
# as a daily rollup: one-day windows aligned to UTC midnight with a one-day granularity, so every
# window holds exactly one bucket per entity. Only complete days are requested.
METRICS_WINDOW_MS = 24 * 60 * 60 * 1000
METRICS_DEFAULT_LOOKBACK_DAYS = 7
# An incremental run never reaches further back than this, so a bogus (e.g. epoch-zero) bucket
# timestamp from the host can't turn every later sync into a day-by-day walk from 1970.
METRICS_MAX_LOOKBACK_DAYS = 31
# Golden signals. Each aggregation is one the spec allows for its metric.
APPLICATION_METRICS: list[dict[str, str]] = [
    {"metric": "calls", "aggregation": "SUM"},
    {"metric": "erroneousCalls", "aggregation": "SUM"},
    {"metric": "errors", "aggregation": "MEAN"},
    {"metric": "latency", "aggregation": "MEAN"},
    {"metric": "latency", "aggregation": "P50"},
    {"metric": "latency", "aggregation": "P90"},
    {"metric": "latency", "aggregation": "P99"},
]

# `/api/apdex/report/{apdexId}` requires a `from`/`to` window. Each sync replaces the table with
# the scores over the trailing window.
APDEX_REPORT_WINDOW_MS = 7 * 24 * 60 * 60 * 1000

PaginationStyle = Literal["page", "offset", "none"]


@frozen
class InstanaFanOutConfig:
    # Endpoint whose rows are walked to build each child request.
    parent: str
    # Field on the parent row substituted into the child `path`.
    parent_field: str
    # Column the parent id is written to on every child row, so rows stay attributable.
    child_field: str


@frozen
class InstanaEndpointConfig:
    name: str
    path: str
    # Key in the response body holding the list of records. ``None`` means the body itself is the list.
    data_path: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    pagination: PaginationStyle = "none"
    fan_out: Optional[InstanaFanOutConfig] = None
    # Only `events` filters server-side (from/to epoch-ms window on the event `start`); everything
    # else is a config/topology catalog with no updated-since cursor, so it ships full refresh.
    is_events: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Extra query params sent on every request.
    extra_params: dict[str, str] = field(default_factory=dict)
    # Set on the application-monitoring metrics endpoints: the key in each response item holding
    # the entity (`application`, `service` or `endpoint`) the metrics belong to.
    metrics_entity: Optional[str] = None
    # Fan-out children that require a time window get `from`/`to` covering this trailing span.
    report_window_ms: Optional[int] = None

    @property
    def supports_incremental(self) -> bool:
        return self.is_events or self.metrics_entity is not None


def _start_incremental_fields() -> list[IncrementalField]:
    # Instana timestamps are epoch milliseconds (int64), not ISO datetimes.
    return [
        {
            "label": "start",
            "type": IncrementalFieldType.Integer,
            "field": "start",
            "field_type": IncrementalFieldType.Integer,
        }
    ]


def _timestamp_incremental_fields() -> list[IncrementalField]:
    return [
        {
            "label": "timestamp",
            "type": IncrementalFieldType.Integer,
            "field": "timestamp",
            "field_type": IncrementalFieldType.Integer,
        }
    ]


# Endpoint catalog, verified against the official OpenAPI spec
# (https://instana.github.io/openapi/openapi.yaml). Instana has no Airbyte/Fivetran connector to
# mirror, so coverage follows what the UI surfaces: events, the application-monitoring catalogs
# (applications/services/endpoints) and their daily golden-signal metrics, website, mobile app and
# synthetic monitoring configs, alerting settings, event specifications, releases, SLOs, Apdex, and
# the infrastructure snapshot inventory. Trace analytics and synthetic result endpoints are
# POST-with-body cursor APIs and are intentionally out of scope.
INSTANA_ENDPOINTS: dict[str, InstanaEndpointConfig] = {
    "events": InstanaEndpointConfig(
        name="events",
        path="/api/events",
        primary_keys=["eventId"],
        is_events=True,
        incremental_fields=_start_incremental_fields(),
    ),
    "applications": InstanaEndpointConfig(
        name="applications",
        path="/api/application-monitoring/applications",
        data_path="items",
        pagination="page",
    ),
    "services": InstanaEndpointConfig(
        name="services",
        path="/api/application-monitoring/services",
        data_path="items",
        pagination="page",
    ),
    "endpoints": InstanaEndpointConfig(
        name="endpoints",
        path="/api/application-monitoring/applications/services/endpoints",
        data_path="items",
        pagination="page",
    ),
    "websites": InstanaEndpointConfig(
        name="websites",
        path="/api/website-monitoring/config",
    ),
    "synthetic_tests": InstanaEndpointConfig(
        name="synthetic_tests",
        path="/api/synthetics/settings/tests",
    ),
    "alerting_channels": InstanaEndpointConfig(
        name="alerting_channels",
        path="/api/events/settings/alertingChannels",
    ),
    "alert_configs": InstanaEndpointConfig(
        name="alert_configs",
        path="/api/events/settings/alerts",
    ),
    "infrastructure_snapshots": InstanaEndpointConfig(
        name="infrastructure_snapshots",
        path="/api/infrastructure-monitoring/snapshots",
        data_path="items",
        primary_keys=["snapshotId"],
        extra_params={"windowSize": str(SNAPSHOTS_WINDOW_MS), "size": str(SNAPSHOTS_MAX_SIZE)},
    ),
    "built_in_event_specifications": InstanaEndpointConfig(
        name="built_in_event_specifications",
        path="/api/events/settings/event-specifications/built-in",
    ),
    "custom_event_specifications": InstanaEndpointConfig(
        name="custom_event_specifications",
        path="/api/events/settings/event-specifications/custom",
    ),
    # `from`/`to` only bound releases by time, and releases are edited in place (`lastUpdated`),
    # so a start-windowed incremental sync would miss edits. The list is small; full refresh.
    "releases": InstanaEndpointConfig(
        name="releases",
        path="/api/releases",
    ),
    "slo_configs": InstanaEndpointConfig(
        name="slo_configs",
        path="/api/settings/slo",
        data_path="items",
        pagination="page",
    ),
    # One report per SLO over the SLO's own time window (no `from`/`to` sent), so each sync
    # replaces the table with current attainment and error budget.
    "slo_reports": InstanaEndpointConfig(
        name="slo_reports",
        path="/api/slo/report/{sloId}",
        primary_keys=["sloId", "fromTimestamp"],
        fan_out=InstanaFanOutConfig(parent="slo_configs", parent_field="id", child_field="sloId"),
    ),
    "synthetic_test_ci_cds": InstanaEndpointConfig(
        name="synthetic_test_ci_cds",
        path="/api/synthetics/settings/tests/ci-cd",
        primary_keys=["testResultId"],
        pagination="offset",
    ),
    "synthetic_locations": InstanaEndpointConfig(
        name="synthetic_locations",
        path="/api/synthetics/settings/locations",
        pagination="offset",
    ),
    "synthetic_datacenters": InstanaEndpointConfig(
        name="synthetic_datacenters",
        path="/api/synthetics/settings/datacenters",
        primary_keys=["datacenterId"],
    ),
    "mobile_apps": InstanaEndpointConfig(
        name="mobile_apps",
        path="/api/mobile-app-monitoring/config",
    ),
    "application_metrics": InstanaEndpointConfig(
        name="application_metrics",
        path="/api/application-monitoring/metrics/applications",
        data_path="items",
        primary_keys=["applicationId", "timestamp"],
        metrics_entity="application",
        incremental_fields=_timestamp_incremental_fields(),
    ),
    "service_metrics": InstanaEndpointConfig(
        name="service_metrics",
        path="/api/application-monitoring/metrics/services",
        data_path="items",
        primary_keys=["serviceId", "timestamp"],
        metrics_entity="service",
        incremental_fields=_timestamp_incremental_fields(),
    ),
    "endpoint_metrics": InstanaEndpointConfig(
        name="endpoint_metrics",
        path="/api/application-monitoring/metrics/endpoints",
        data_path="items",
        primary_keys=["endpointId", "timestamp"],
        metrics_entity="endpoint",
        incremental_fields=_timestamp_incremental_fields(),
    ),
    "apdex_configs": InstanaEndpointConfig(
        name="apdex_configs",
        path="/api/settings/apdex",
    ),
    "apdex_reports": InstanaEndpointConfig(
        name="apdex_reports",
        path="/api/apdex/report/{apdexId}",
        primary_keys=["apdexId", "from"],
        fan_out=InstanaFanOutConfig(parent="apdex_configs", parent_field="id", child_field="apdexId"),
        report_window_ms=APDEX_REPORT_WINDOW_MS,
    ),
}

ENDPOINTS = tuple(INSTANA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in INSTANA_ENDPOINTS.items()
}
