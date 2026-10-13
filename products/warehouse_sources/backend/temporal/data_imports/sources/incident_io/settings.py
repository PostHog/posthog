import dataclasses
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import UNVERSIONED_API_VERSION
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# incident.io versions each resource's path on its own track (/v1, /v2, /v3), so the source-level
# label is opaque: "v1" is the original endpoint set; "v3" moves follow_ups from GET /v2/follow_ups,
# which incident.io removes on 2026-12-31, to its GET /v3/follow_ups successor. Every other
# resource reads the same path under both labels.
INCIDENT_IO_API_VERSION_V1 = UNVERSIONED_API_VERSION
INCIDENT_IO_API_VERSION_V3 = "v3"
INCIDENT_IO_SUPPORTED_VERSIONS = (INCIDENT_IO_API_VERSION_V1, INCIDENT_IO_API_VERSION_V3)
INCIDENT_IO_DEFAULT_API_VERSION = INCIDENT_IO_API_VERSION_V3


@dataclass(frozen=True)
class EntryWindow:
    """A rolling time window sent as a pair of query params, anchored on the sync's start time."""

    start_param: str
    end_param: str
    lookback: timedelta
    lookahead: timedelta


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
    # None for a paginated endpoint that takes no page-size param.
    page_size_param: Optional[str] = "page_size"
    # Query param the `pagination_meta.after` cursor is replayed as.
    cursor_param: str = "after"
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
    # Required time window for endpoints that return nothing older than "now" without one.
    entry_window: Optional[EntryWindow] = None
    # Top-level response fields never written to the warehouse, e.g. credentials.
    excluded_fields: tuple[str, ...] = ()

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

# Schedule entries don't carry their schedule's id, so it's copied from the parent row.
_SCHEDULE_ENTRIES_FANOUT = DependentEndpointConfig(
    parent_name="schedules",
    resolve_param="schedule_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "schedule_id"},
    parent_params={"page_size": 250},
)

_STATUS_PAGE_INCIDENTS_FANOUT = DependentEndpointConfig(
    parent_name="status_pages",
    resolve_param="status_page_id",
    resolve_field="id",
    include_from_parent=[],
    parent_params={"page_size": 250},
)

# Full refresh re-reads this window on every sync, so shifts older than the lookback drop out of the table.
_SCHEDULE_ENTRIES_WINDOW = EntryWindow(
    start_param="entry_window_start",
    end_param="entry_window_end",
    lookback=timedelta(days=365),
    lookahead=timedelta(days=30),
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
    "schedule_entries": IncidentIoEndpointConfig(
        name="schedule_entries",
        # `{schedule_id}` is bound per parent schedule row by the fan-out.
        path="/v2/schedule_entries?schedule_id={schedule_id}",
        # `final` is the effective rota after overrides are merged in.
        data_key="schedule_entries.final",
        paginated=True,
        page_size_param=None,
        # The next-page cursor replaces the window start; the window end stays fixed.
        cursor_param="entry_window_start",
        # Entries carry no id of their own that the API guarantees; a fingerprint names the shift
        # and an override can split one shift into several entries, so the start time is part of the key.
        primary_keys=["schedule_id", "fingerprint", "start_at"],
        partition_key="start_at",
        fanout=_SCHEDULE_ENTRIES_FANOUT,
        entry_window=_SCHEDULE_ENTRIES_WINDOW,
    ),
    "escalation_paths": IncidentIoEndpointConfig(
        name="escalation_paths",
        path="/v2/escalation_paths",
        data_key="escalation_paths",
        paginated=True,
        page_size=25,
    ),
    "alert_sources": IncidentIoEndpointConfig(
        name="alert_sources",
        path="/v2/alert_sources",
        data_key="alert_sources",
        # The token lets anyone push alerts into the account, so it never reaches the warehouse.
        excluded_fields=("secret_token",),
    ),
    "status_pages": IncidentIoEndpointConfig(
        name="status_pages",
        path="/v2/status_pages",
        data_key="status_pages",
        paginated=True,
        page_size=250,
    ),
    "status_page_incidents": IncidentIoEndpointConfig(
        name="status_page_incidents",
        # `{status_page_id}` is bound per parent status page row by the fan-out.
        path="/v2/status_page_incidents?status_page_id={status_page_id}",
        data_key="status_page_incidents",
        paginated=True,
        page_size=250,
        primary_keys=["status_page_id", "id"],
        partition_key="published_at",
        fanout=_STATUS_PAGE_INCIDENTS_FANOUT,
    ),
}

INCIDENT_IO_ENDPOINTS_V3: dict[str, IncidentIoEndpointConfig] = {
    **INCIDENT_IO_ENDPOINTS,
    # Same rows as v2 plus a `category` object, now paged by `pagination_meta.after` with a 250 cap.
    "follow_ups": dataclasses.replace(INCIDENT_IO_ENDPOINTS["follow_ups"], path="/v3/follow_ups"),
}

INCIDENT_IO_ENDPOINTS_BY_VERSION: dict[str, dict[str, IncidentIoEndpointConfig]] = {
    INCIDENT_IO_API_VERSION_V1: INCIDENT_IO_ENDPOINTS,
    INCIDENT_IO_API_VERSION_V3: INCIDENT_IO_ENDPOINTS_V3,
}


def endpoints_for_version(api_version: str) -> dict[str, IncidentIoEndpointConfig]:
    # An undeclared pin raises rather than falling back, so a sync never drifts onto another version's paths.
    try:
        return INCIDENT_IO_ENDPOINTS_BY_VERSION[api_version]
    except KeyError as e:
        raise ValueError(
            f"Unsupported incident.io API version {api_version!r}; supported: {INCIDENT_IO_SUPPORTED_VERSIONS}"
        ) from e


# The table set is identical across versions, so discovery never orphans a table on repin.
ENDPOINTS = tuple(INCIDENT_IO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in INCIDENT_IO_ENDPOINTS.items() if config.incremental_fields
}
