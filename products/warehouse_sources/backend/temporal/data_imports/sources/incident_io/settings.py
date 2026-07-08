from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class IncidentIoEndpointConfig:
    name: str
    # Versioned path — incident.io mixes /v1 and /v2 across resources.
    path: str
    # Key the list of objects is nested under in the response body (e.g. {"incidents": [...]}).
    data_key: str
    # Small config-style endpoints (severities, statuses, ...) return the full list in one
    # response and accept no pagination params.
    paginated: bool = False
    page_size: int = 250
    primary_key: str = "id"
    # Fields with a documented server-side `<field>[gte]` filter on the list endpoint.
    # Endpoints without one are full refresh only.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field used for datetime partitioning. Never an updated_at-style
    # field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    # Server-side sort. Only the incidents list supports sorting; `created_at_oldest_first`
    # keeps pages stable and lets the incremental watermark advance monotonically.
    sort_by: Optional[str] = None


_DATETIME_INCREMENTAL_FIELD_CREATED_AT: IncrementalField = {
    "label": "created_at",
    "type": IncrementalFieldType.DateTime,
    "field": "created_at",
    "field_type": IncrementalFieldType.DateTime,
}

_DATETIME_INCREMENTAL_FIELD_UPDATED_AT: IncrementalField = {
    "label": "updated_at",
    "type": IncrementalFieldType.DateTime,
    "field": "updated_at",
    "field_type": IncrementalFieldType.DateTime,
}


# Alerts and escalations also document `created_at[gte]` filters, but neither endpoint
# accepts a sort param and the default ordering is undocumented, so we keep them full
# refresh rather than risk an unstable incremental watermark.
INCIDENT_IO_ENDPOINTS: dict[str, IncidentIoEndpointConfig] = {
    "incidents": IncidentIoEndpointConfig(
        name="incidents",
        path="/v2/incidents",
        data_key="incidents",
        paginated=True,
        page_size=250,
        partition_key="created_at",
        sort_by="created_at_oldest_first",
        incremental_fields=[
            _DATETIME_INCREMENTAL_FIELD_UPDATED_AT,
            _DATETIME_INCREMENTAL_FIELD_CREATED_AT,
        ],
    ),
    "incident_updates": IncidentIoEndpointConfig(
        name="incident_updates",
        path="/v2/incident_updates",
        data_key="incident_updates",
        paginated=True,
        page_size=250,
        partition_key="created_at",
    ),
    "follow_ups": IncidentIoEndpointConfig(
        name="follow_ups",
        path="/v2/follow_ups",
        data_key="follow_ups",
        paginated=True,
        page_size=250,
        partition_key="created_at",
    ),
    "alerts": IncidentIoEndpointConfig(
        name="alerts",
        path="/v2/alerts",
        data_key="alerts",
        paginated=True,
        # The alerts list caps page_size at 50, unlike incidents' 250.
        page_size=50,
        partition_key="created_at",
    ),
    "escalations": IncidentIoEndpointConfig(
        name="escalations",
        path="/v2/escalations",
        data_key="escalations",
        paginated=True,
        page_size=50,
        partition_key="created_at",
    ),
    "users": IncidentIoEndpointConfig(
        name="users",
        path="/v2/users",
        data_key="users",
        paginated=True,
        page_size=250,
    ),
    "schedules": IncidentIoEndpointConfig(
        name="schedules",
        path="/v2/schedules",
        data_key="schedules",
        paginated=True,
        page_size=250,
        partition_key="created_at",
    ),
    "severities": IncidentIoEndpointConfig(
        name="severities",
        path="/v1/severities",
        data_key="severities",
    ),
    "incident_roles": IncidentIoEndpointConfig(
        name="incident_roles",
        path="/v2/incident_roles",
        data_key="incident_roles",
    ),
    "incident_statuses": IncidentIoEndpointConfig(
        name="incident_statuses",
        path="/v1/incident_statuses",
        data_key="incident_statuses",
    ),
    "incident_types": IncidentIoEndpointConfig(
        name="incident_types",
        path="/v1/incident_types",
        data_key="incident_types",
    ),
    "custom_fields": IncidentIoEndpointConfig(
        name="custom_fields",
        path="/v2/custom_fields",
        data_key="custom_fields",
    ),
}

ENDPOINTS = tuple(INCIDENT_IO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in INCIDENT_IO_ENDPOINTS.items() if config.incremental_fields
}
