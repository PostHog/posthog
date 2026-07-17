from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# incident.io versions its API per-resource and runs versions in parallel — some resources
# expose only /v1, some only /v2, and a few both. These are opaque source-level pins that map
# onto the per-resource paths below; they are never parsed or ordered.
INCIDENT_IO_API_VERSION_V1 = "v1"
INCIDENT_IO_API_VERSION_V2 = "v2"
SUPPORTED_API_VERSIONS = (INCIDENT_IO_API_VERSION_V1, INCIDENT_IO_API_VERSION_V2)
DEFAULT_API_VERSION = INCIDENT_IO_API_VERSION_V2


@dataclass
class IncidentIoEndpointConfig:
    name: str
    # Request path per source-level API version. Many resources exist on a single version;
    # incidents, incident_roles and custom_fields expose both. `path_for` resolves a source's
    # pin against this map, falling back to the version the resource actually offers.
    paths: dict[str, str]
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

    def path_for(self, api_version: str) -> str:
        """Request path for a source's pinned API version.

        Honors the pin when this resource offers that version; otherwise falls back to the
        default version, then to whatever single version the resource exposes — several
        incident.io resources only exist on one version regardless of the source pin.
        """
        return self.paths.get(api_version) or self.paths.get(DEFAULT_API_VERSION) or next(iter(self.paths.values()))


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
# Paths are pinned to the version each resource is actually synced from today, so both the "v1"
# and "v2" source pins resolve to identical URLs — existing sources were backfilled to "v1" by
# migration 0075, so a "v1" pin must keep hitting the same endpoints, not a different /v1 list.
# The incidents list only gained server-side sorting and `[gte]` filters in v2 (the v1 list is
# deprecated and offers neither), and incident_roles / custom_fields already sync from /v2, so all
# three stay v2-only here. severities / incident_statuses / incident_types exist only on /v1.
# The per-version map is the seam for a future bump that genuinely moves a resource's endpoint —
# that change would repin affected rows in its own migration (see the skill).
INCIDENT_IO_ENDPOINTS: dict[str, IncidentIoEndpointConfig] = {
    "incidents": IncidentIoEndpointConfig(
        name="incidents",
        paths={INCIDENT_IO_API_VERSION_V2: "/v2/incidents"},
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
        paths={INCIDENT_IO_API_VERSION_V2: "/v2/incident_updates"},
        data_key="incident_updates",
        paginated=True,
        page_size=250,
        partition_key="created_at",
    ),
    "follow_ups": IncidentIoEndpointConfig(
        name="follow_ups",
        paths={INCIDENT_IO_API_VERSION_V2: "/v2/follow_ups"},
        data_key="follow_ups",
        paginated=True,
        page_size=250,
        partition_key="created_at",
    ),
    "alerts": IncidentIoEndpointConfig(
        name="alerts",
        paths={INCIDENT_IO_API_VERSION_V2: "/v2/alerts"},
        data_key="alerts",
        paginated=True,
        # The alerts list caps page_size at 50, unlike incidents' 250.
        page_size=50,
        partition_key="created_at",
    ),
    "escalations": IncidentIoEndpointConfig(
        name="escalations",
        paths={INCIDENT_IO_API_VERSION_V2: "/v2/escalations"},
        data_key="escalations",
        paginated=True,
        page_size=50,
        partition_key="created_at",
    ),
    "users": IncidentIoEndpointConfig(
        name="users",
        paths={INCIDENT_IO_API_VERSION_V2: "/v2/users"},
        data_key="users",
        paginated=True,
        page_size=250,
    ),
    "schedules": IncidentIoEndpointConfig(
        name="schedules",
        paths={INCIDENT_IO_API_VERSION_V2: "/v2/schedules"},
        data_key="schedules",
        paginated=True,
        page_size=250,
        partition_key="created_at",
    ),
    "severities": IncidentIoEndpointConfig(
        name="severities",
        paths={INCIDENT_IO_API_VERSION_V1: "/v1/severities"},
        data_key="severities",
    ),
    "incident_roles": IncidentIoEndpointConfig(
        name="incident_roles",
        paths={INCIDENT_IO_API_VERSION_V2: "/v2/incident_roles"},
        data_key="incident_roles",
    ),
    "incident_statuses": IncidentIoEndpointConfig(
        name="incident_statuses",
        paths={INCIDENT_IO_API_VERSION_V1: "/v1/incident_statuses"},
        data_key="incident_statuses",
    ),
    "incident_types": IncidentIoEndpointConfig(
        name="incident_types",
        paths={INCIDENT_IO_API_VERSION_V1: "/v1/incident_types"},
        data_key="incident_types",
    ),
    "custom_fields": IncidentIoEndpointConfig(
        name="custom_fields",
        paths={INCIDENT_IO_API_VERSION_V2: "/v2/custom_fields"},
        data_key="custom_fields",
    ),
}

ENDPOINTS = tuple(INCIDENT_IO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in INCIDENT_IO_ENDPOINTS.items() if config.incremental_fields
}
