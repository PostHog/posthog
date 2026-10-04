from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
class IncidentIoEndpointConfig:
    name: str
    # Versioned path — incident.io mixes /v1, /v2 and /v3 across resources.
    path: str
    # Key the list of objects is nested under in the response body (e.g. {"incidents": [...]}).
    data_key: str
    # Small config-style endpoints (severities, statuses, ...) return the full list in one
    # response and accept no pagination params.
    paginated: bool = False
    page_size: int = 250
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Fields with a documented server-side `<field>[gte]` filter on the list endpoint.
    # Endpoints without one are full refresh only.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field used for datetime partitioning. Never an updated_at-style
    # field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    # Server-side sort. Only the incidents list supports sorting; `created_at_oldest_first`
    # keeps pages stable and lets the incremental watermark advance monotonically.
    sort_by: Optional[str] = None
    # Set for endpoints that require a parent id filter and so are fetched once per parent row.
    fanout: Optional[DependentEndpointConfig] = None

    @property
    def default_incremental_field(self) -> Optional[str]:
        # Read by the fan-out helper only for incremental children; every fan-out here is full refresh.
        return None


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


# The child rows already carry the parent id, so nothing is copied from the parent row.
_CATALOG_ENTRIES_FANOUT = DependentEndpointConfig(
    parent_name="catalog_types",
    resolve_param="catalog_type_id",
    resolve_field="id",
    include_from_parent=[],
)

_CUSTOM_FIELD_OPTIONS_FANOUT = DependentEndpointConfig(
    parent_name="custom_fields",
    resolve_param="custom_field_id",
    resolve_field="id",
    include_from_parent=[],
)


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
    "custom_field_options": IncidentIoEndpointConfig(
        name="custom_field_options",
        # `{custom_field_id}` is bound per parent custom field row by the fan-out.
        path="/v1/custom_field_options?custom_field_id={custom_field_id}",
        data_key="custom_field_options",
        paginated=True,
        page_size=250,
        primary_keys=["custom_field_id", "id"],
        fanout=_CUSTOM_FIELD_OPTIONS_FANOUT,
    ),
    "incident_timestamps": IncidentIoEndpointConfig(
        name="incident_timestamps",
        path="/v2/incident_timestamps",
        data_key="incident_timestamps",
    ),
    "incident_alerts": IncidentIoEndpointConfig(
        name="incident_alerts",
        path="/v2/incident_alerts",
        data_key="incident_alerts",
        paginated=True,
        page_size=50,
    ),
    "catalog_types": IncidentIoEndpointConfig(
        name="catalog_types",
        path="/v3/catalog_types",
        data_key="catalog_types",
        partition_key="created_at",
    ),
    "catalog_entries": IncidentIoEndpointConfig(
        name="catalog_entries",
        # `{catalog_type_id}` is bound per parent catalog type row by the fan-out.
        path="/v3/catalog_entries?catalog_type_id={catalog_type_id}",
        data_key="catalog_entries",
        paginated=True,
        page_size=250,
        primary_keys=["catalog_type_id", "id"],
        partition_key="created_at",
        fanout=_CATALOG_ENTRIES_FANOUT,
    ),
}

ENDPOINTS = tuple(INCIDENT_IO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in INCIDENT_IO_ENDPOINTS.items() if config.incremental_fields
}
