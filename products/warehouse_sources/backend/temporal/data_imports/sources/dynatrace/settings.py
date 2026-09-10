from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Dynatrace timestamps (startTime, endTime, timestamp, firstSeenTms, ...) are integers in UTC
# milliseconds, not ISO datetimes, so no endpoint declares a datetime partition key — an epoch-ms
# integer isn't a safe partition key for `partition_mode="datetime"`.


@dataclass
class DynatraceEndpointConfig:
    name: str
    path: str
    # Key in the response body holding the list of records (e.g. "problems", "events").
    data_key: str
    primary_key: str = "id"
    page_size: int = 100
    # Server-side timeframe filter: the endpoint accepts `from`/`to` params. Only endpoints where
    # the docs guarantee a genuine server-side time filter are marked incremental via this.
    supports_time_filter: bool = False
    # Row field the incremental watermark tracks (epoch-ms integer, e.g. startTime / timestamp).
    incremental_field: Optional[str] = None
    # Relative `from` value seeded on the first sync / full refresh of time-filtered endpoints,
    # since Dynatrace defaults to very narrow windows (problems/events: now-2h) when `from` is
    # omitted. Dynatrace relative format: now-NU with units m, h, d, w, M, y.
    default_from: Optional[str] = None
    # Required `entitySelector` for the entities endpoint (must specify a type on the first page).
    entity_selector: Optional[str] = None
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
        primary_key="entityId",
        page_size=100,
        entity_selector=f'type("{entity_type}")',
        default_from="now-30d",
        extra_params={"fields": _ENTITY_FIELDS},
    )


# Endpoint catalog for the Dynatrace Environment API v2. Coverage follows the streams an
# SRE/observability team wants in a warehouse: problem history, events, audit trail,
# vulnerabilities, entity inventory, metric catalog, and SLO status.
#
# Incremental vs full refresh: only problems, events, and audit logs expose a documented
# server-side `from`/`to` timeframe filter, so only those are marked incremental. The rest are
# full refresh and dedupe on their primary key.
DYNATRACE_ENDPOINTS: dict[str, DynatraceEndpointConfig] = {
    "problems": DynatraceEndpointConfig(
        name="problems",
        path="/api/v2/problems",
        data_key="problems",
        primary_key="problemId",
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
        primary_key="eventId",
        page_size=1000,
        supports_time_filter=True,
        incremental_field="startTime",
        default_from="now-30d",
    ),
    "audit_logs": DynatraceEndpointConfig(
        name="audit_logs",
        path="/api/v2/auditlogs",
        data_key="auditLogs",
        primary_key="logId",
        page_size=1000,
        supports_time_filter=True,
        incremental_field="timestamp",
        default_from="now-30d",
    ),
    "security_problems": DynatraceEndpointConfig(
        name="security_problems",
        path="/api/v2/securityProblems",
        data_key="securityProblems",
        primary_key="securityProblemId",
        page_size=100,
    ),
    "hosts": _entity_endpoint("hosts", "HOST"),
    "services": _entity_endpoint("services", "SERVICE"),
    "applications": _entity_endpoint("applications", "APPLICATION"),
    "process_groups": _entity_endpoint("process_groups", "PROCESS_GROUP"),
    "metrics": DynatraceEndpointConfig(
        name="metrics",
        path="/api/v2/metrics",
        data_key="metrics",
        primary_key="metricId",
        page_size=500,
        extra_params={"fields": "+created,+lastWritten,+entityType,+aggregationTypes,+tags"},
    ),
    "slos": DynatraceEndpointConfig(
        name="slos",
        path="/api/v2/slo",
        data_key="slo",
        primary_key="id",
        # With `evaluate=true` (needed for status / error budget) the endpoint caps pageSize at 25.
        page_size=25,
        extra_params={"evaluate": "true"},
    ),
}

ENDPOINTS = tuple(DYNATRACE_ENDPOINTS.keys())

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
    "hosts": "entities.read",
    "services": "entities.read",
    "applications": "entities.read",
    "process_groups": "entities.read",
    "metrics": "metrics.read",
    "slos": "slo.read",
}
