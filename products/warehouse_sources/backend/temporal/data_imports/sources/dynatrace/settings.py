from dataclasses import field
from datetime import timedelta
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Dynatrace timestamps (startTime, endTime, timestamp, firstSeenTms, ...) are integers in UTC
# milliseconds, not ISO datetimes, so no endpoint declares a datetime partition key — an epoch-ms
# integer isn't a safe partition key for `partition_mode="datetime"`.


@frozen
class DynatraceEndpointConfig:
    name: str
    path: str
    # Key in the response body holding the list of records (e.g. "problems", "events").
    data_key: str
    # Row fields that identify a record. A tuple is needed where no single field is unique, as on
    # metric data points (one row per metric, dimension tuple and timestamp).
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # None where the endpoint takes no page-size param (the metrics query and both synthetic
    # endpoints return their whole result in one response).
    page_size: Optional[int] = 100
    # Server-side timeframe filter: the endpoint accepts `from`/`to` params. Only endpoints where
    # the docs guarantee a genuine server-side time filter are marked incremental via this.
    supports_time_filter: bool = False
    # Row field the incremental watermark tracks (epoch-ms integer, e.g. startTime / timestamp).
    incremental_field: Optional[str] = None
    # Relative `from` value seeded on the first sync / full refresh of time-filtered endpoints,
    # since Dynatrace defaults to very narrow windows (problems/events: now-2h) when `from` is
    # omitted. Dynatrace relative format: now-NU with units m, h, d, w, M, y.
    default_from: Optional[str] = None
    # Query param carrying the start of the window. The synthetic executions endpoint names its
    # timeframe params after the timestamp they filter on rather than plain `from`/`to`.
    time_filter_param: str = "from"
    # Longest window the endpoint serves. Watermarks older than this are clamped, so an
    # incremental run never asks for a timeframe Dynatrace refuses.
    max_lookback: Optional[timedelta] = None
    # Required `entitySelector` for the entities endpoint (must specify a type on the first page).
    entity_selector: Optional[str] = None
    # Entity type the selector pins. Also the set the tags endpoint is fanned out over.
    entity_type: Optional[str] = None
    # Endpoint has no listing of its own: Dynatrace requires an `entitySelector` naming a single
    # entity type, so it is read once per type the entity tables cover.
    fans_out_over_entity_types: bool = False
    # Endpoint whose path stands in for this one when probing token scope. The metrics query needs
    # a metric selector a probe has no way to guess, so it borrows the descriptor endpoint's probe
    # — both sit behind `metrics.read`.
    scope_probe_endpoint: Optional[str] = None
    # Endpoint syncs nothing until the user names the metrics they want.
    requires_metric_selector: bool = False
    # Extra query params sent on the first page only — follow-up pages must carry nothing but
    # `nextPageKey` (the key encodes the original query).
    extra_params: dict[str, str] = field(default_factory=dict)

    @property
    def incremental_fields(self) -> list[IncrementalField]:
        if not self.supports_time_filter or not self.incremental_field:
            return []
        return [
            {
                "label": self.incremental_field,
                "type": IncrementalFieldType.Integer,
                "field": self.incremental_field,
                "field_type": IncrementalFieldType.Integer,
            }
        ]


# Entity inventory tables share the entities endpoint, fanned out by type. `from` bounds the
# activity window (entities endpoint defaults to now-3d, which would drop hosts idle over a
# weekend), and `fields` adds the properties/tags the default response omits.
_ENTITY_FIELDS = "+firstSeenTms,+lastSeenTms,+properties,+tags,+managementZones"


def _entity_endpoint(name: str, entity_type: str) -> DynatraceEndpointConfig:
    return DynatraceEndpointConfig(
        name=name,
        path="/api/v2/entities",
        data_key="entities",
        primary_keys=["entityId"],
        page_size=100,
        entity_selector=f'type("{entity_type}")',
        entity_type=entity_type,
        default_from="now-30d",
        extra_params={"fields": _ENTITY_FIELDS},
    )


# Endpoint catalog for the Dynatrace Environment API. Coverage follows the streams an
# SRE/observability team wants in a warehouse: problem history, events, audit trail,
# vulnerabilities, entity inventory, metric catalog and values, SLO status, and synthetic
# availability.
#
# Incremental vs full refresh: problems, events, audit logs, metric data points and synthetic
# executions expose a documented server-side timeframe filter, so only those are marked
# incremental. The rest are full refresh and dedupe on their primary key.
DYNATRACE_ENDPOINTS: dict[str, DynatraceEndpointConfig] = {
    "problems": DynatraceEndpointConfig(
        name="problems",
        path="/api/v2/problems",
        data_key="problems",
        primary_keys=["problemId"],
        page_size=500,
        supports_time_filter=True,
        incremental_field="startTime",
        # Without `from` Dynatrace only returns the last 2 hours of problems.
        default_from="now-365d",
    ),
    "events": DynatraceEndpointConfig(
        name="events",
        path="/api/v2/events",
        data_key="events",
        primary_keys=["eventId"],
        page_size=1000,
        supports_time_filter=True,
        incremental_field="startTime",
        default_from="now-30d",
    ),
    "audit_logs": DynatraceEndpointConfig(
        name="audit_logs",
        path="/api/v2/auditlogs",
        data_key="auditLogs",
        primary_keys=["logId"],
        page_size=1000,
        supports_time_filter=True,
        incremental_field="timestamp",
        default_from="now-30d",
    ),
    "security_problems": DynatraceEndpointConfig(
        name="security_problems",
        path="/api/v2/securityProblems",
        data_key="securityProblems",
        primary_keys=["securityProblemId"],
        page_size=100,
    ),
    "releases": DynatraceEndpointConfig(
        name="releases",
        path="/api/v2/releases",
        data_key="releases",
        # A release carries no id of its own. Dynatrace documents <name, product, stage, version>
        # as the unique tuple.
        primary_keys=["name", "product", "stage", "version"],
        page_size=1000,
        # Dynatrace falls back to the last two weeks when `from` is omitted. A release row carries
        # no timestamp to track a watermark on, so the table is full refresh over a wider window.
        default_from="now-30d",
    ),
    "entity_types": DynatraceEndpointConfig(
        name="entity_types",
        path="/api/v2/entityTypes",
        data_key="types",
        primary_keys=["type"],
        page_size=500,
    ),
    "hosts": _entity_endpoint("hosts", "HOST"),
    "services": _entity_endpoint("services", "SERVICE"),
    "applications": _entity_endpoint("applications", "APPLICATION"),
    "process_groups": _entity_endpoint("process_groups", "PROCESS_GROUP"),
    "databases": _entity_endpoint("databases", "RELATIONAL_DATABASE_SERVICE"),
    "disks": _entity_endpoint("disks", "DISK"),
    "queues": _entity_endpoint("queues", "QUEUE"),
    "kubernetes_clusters": _entity_endpoint("kubernetes_clusters", "KUBERNETES_CLUSTER"),
    "kubernetes_nodes": _entity_endpoint("kubernetes_nodes", "KUBERNETES_NODE"),
    "cloud_applications": _entity_endpoint("cloud_applications", "CLOUD_APPLICATION"),
    "custom_devices": _entity_endpoint("custom_devices", "CUSTOM_DEVICE"),
    "entity_tags": DynatraceEndpointConfig(
        name="entity_tags",
        path="/api/v2/tags",
        data_key="tags",
        # Dynatrace returns no identifier for a tag, and the same tag sits on entities of several
        # types, so a row is keyed on the type it was read for plus the tag's canonical string
        # form, which already carries the context, key and value.
        primary_keys=["entityType", "stringRepresentation"],
        # The endpoint takes no pageSize and returns every matching tag in one response.
        page_size=None,
        # Without `from` the endpoint only looks back 24 hours, so tags on entities idle over a
        # weekend would disappear from the table.
        default_from="now-30d",
        fans_out_over_entity_types=True,
        scope_probe_endpoint="hosts",
    ),
    "metrics": DynatraceEndpointConfig(
        name="metrics",
        path="/api/v2/metrics",
        data_key="metrics",
        primary_keys=["metricId"],
        page_size=500,
        extra_params={"fields": "+created,+lastWritten,+entityType,+aggregationTypes,+tags"},
    ),
    "metric_data_points": DynatraceEndpointConfig(
        name="metric_data_points",
        path="/api/v2/metrics/query",
        data_key="result",
        primary_keys=["metricId", "dimensionKey", "timestamp"],
        # The query endpoint takes no pageSize, and its nextPageKey is documented as always null:
        # one request returns the whole timeframe.
        page_size=None,
        supports_time_filter=True,
        incremental_field="timestamp",
        default_from="now-30d",
        requires_metric_selector=True,
        scope_probe_endpoint="metrics",
        # Without a resolution Dynatrace spreads a fixed 120 data points over whatever timeframe
        # was asked for, so the grain would shift between the first sync and later ones.
        extra_params={"resolution": "1h"},
    ),
    "slos": DynatraceEndpointConfig(
        name="slos",
        path="/api/v2/slo",
        data_key="slo",
        primary_keys=["id"],
        # With `evaluate=true` (needed for status / error budget) the endpoint caps pageSize at 25.
        page_size=25,
        extra_params={"evaluate": "true"},
    ),
    "synthetic_monitors": DynatraceEndpointConfig(
        name="synthetic_monitors",
        # The v2 monitor listing needs the broad `settings.read` scope and currently covers only
        # browser and multi-protocol monitors, so the source reads the v1 listing instead.
        path="/api/v1/synthetic/monitors",
        data_key="monitors",
        primary_keys=["entityId"],
        page_size=None,
    ),
    "synthetic_executions": DynatraceEndpointConfig(
        name="synthetic_executions",
        path="/api/v2/synthetic/executions",
        data_key="executions",
        primary_keys=["executionId"],
        page_size=None,
        supports_time_filter=True,
        incremental_field="executionTimestamp",
        time_filter_param="executionFrom",
        default_from="now-6h",
        max_lookback=timedelta(hours=6),
    ),
}

ENDPOINTS = tuple(DYNATRACE_ENDPOINTS.keys())

# Types the tags endpoint is read for, derived from the entity tables so the two can't drift.
TAGGED_ENTITY_TYPES: tuple[str, ...] = tuple(
    config.entity_type for config in DYNATRACE_ENDPOINTS.values() if config.entity_type
)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DYNATRACE_ENDPOINTS.items()
}

# Token scope each endpoint needs, surfaced in the setup caption and per-endpoint permission
# probes. Scopes are granular per API area, so users only need to grant what they sync.
ENDPOINT_SCOPES: dict[str, str] = {
    "problems": "problems.read",
    "events": "events.read",
    "audit_logs": "auditLogs.read",
    "security_problems": "securityProblems.read",
    "releases": "releases.read",
    "entity_types": "entities.read",
    "hosts": "entities.read",
    "services": "entities.read",
    "applications": "entities.read",
    "process_groups": "entities.read",
    "databases": "entities.read",
    "disks": "entities.read",
    "queues": "entities.read",
    "kubernetes_clusters": "entities.read",
    "kubernetes_nodes": "entities.read",
    "cloud_applications": "entities.read",
    "custom_devices": "entities.read",
    "entity_tags": "entities.read",
    "metrics": "metrics.read",
    "metric_data_points": "metrics.read",
    "slos": "slo.read",
    "synthetic_monitors": "ReadSyntheticData",
    "synthetic_executions": "syntheticExecutions.read",
}
