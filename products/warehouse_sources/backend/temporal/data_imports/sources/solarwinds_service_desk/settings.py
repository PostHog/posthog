from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# The API docs' pagination examples request 100 rows per page; no hard maximum is documented, so we
# stay at the documented example value.
PER_PAGE = 100


def _updated_at_incremental_fields() -> list[IncrementalField]:
    # The server-side `updated_from` filter (ISO 8601 UTC, "until now") keys off `updated_at`.
    return [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


@frozen
class SolarwindsServiceDeskEndpointConfig:
    name: str
    path: str  # Path on the regional API host, e.g. "/incidents.json"
    # Singular resource key some list payloads wrap each row in (e.g. {"problem": {...}}). The
    # official response samples are inconsistent about this, so the transport unwraps defensively.
    wrapper_key: str
    # Only /incidents documents the server-side `updated_from` time filter; every other list
    # endpoint is full refresh (they expose only field-equality search params).
    supports_incremental: bool = False
    # Stable creation-time field to partition by. Only set where the documented response sample
    # actually includes `created_at`.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Record ids are account-unique integers, so `id` is a safe primary key on every top-level endpoint.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Set on child endpoints that only exist nested under a parent record.
    fanout: Optional[DependentEndpointConfig] = None
    page_size: int = PER_PAGE
    default_incremental_field: Optional[str] = None


SOLARWINDS_SERVICE_DESK_ENDPOINTS: dict[str, SolarwindsServiceDeskEndpointConfig] = {
    "incidents": SolarwindsServiceDeskEndpointConfig(
        name="incidents",
        path="/incidents.json",
        wrapper_key="incident",
        supports_incremental=True,
        partition_key="created_at",
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "problems": SolarwindsServiceDeskEndpointConfig(
        name="problems",
        path="/problems.json",
        wrapper_key="problem",
    ),
    "changes": SolarwindsServiceDeskEndpointConfig(
        name="changes",
        path="/changes.json",
        wrapper_key="change",
        partition_key="created_at",
    ),
    "releases": SolarwindsServiceDeskEndpointConfig(
        name="releases",
        path="/releases.json",
        wrapper_key="release",
    ),
    "solutions": SolarwindsServiceDeskEndpointConfig(
        name="solutions",
        path="/solutions.json",
        wrapper_key="solution",
        partition_key="created_at",
    ),
    "catalog_items": SolarwindsServiceDeskEndpointConfig(
        name="catalog_items",
        path="/catalog_items.json",
        wrapper_key="catalog_item",
    ),
    "users": SolarwindsServiceDeskEndpointConfig(
        name="users",
        path="/users.json",
        wrapper_key="user",
    ),
    "groups": SolarwindsServiceDeskEndpointConfig(
        name="groups",
        path="/groups.json",
        wrapper_key="group",
    ),
    "departments": SolarwindsServiceDeskEndpointConfig(
        name="departments",
        path="/departments.json",
        wrapper_key="department",
    ),
    "sites": SolarwindsServiceDeskEndpointConfig(
        name="sites",
        path="/sites.json",
        wrapper_key="site",
    ),
    "hardwares": SolarwindsServiceDeskEndpointConfig(
        name="hardwares",
        path="/hardwares.json",
        wrapper_key="hardware",
    ),
    "other_assets": SolarwindsServiceDeskEndpointConfig(
        name="other_assets",
        path="/other_assets.json",
        wrapper_key="other_asset",
        partition_key="created_at",
    ),
    "categories": SolarwindsServiceDeskEndpointConfig(
        name="categories",
        path="/categories.json",
        wrapper_key="category",
    ),
    "configuration_items": SolarwindsServiceDeskEndpointConfig(
        name="configuration_items",
        path="/configuration_items.json",
        wrapper_key="configuration_item",
        partition_key="created_at",
    ),
    # The account-wide audit list covers every record type, so the per-record
    # /{object_type}/{id}/audits endpoint is not needed.
    "audits": SolarwindsServiceDeskEndpointConfig(
        name="audits",
        path="/audits.json",
        wrapper_key="audit",
        partition_key="created_at",
    ),
    # Time tracks have no account-wide list; they are only reachable under each incident.
    "time_tracks": SolarwindsServiceDeskEndpointConfig(
        name="time_tracks",
        path="/incidents/{incident_id}/time_tracks.json",
        wrapper_key="time_track",
        partition_key="created_at",
        primary_keys=["incident_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="incidents",
            resolve_param="incident_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "incident_id"},
            # An incident deleted between the parent listing and its child fetch has no time tracks to sync.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
}

ENDPOINTS = tuple(SOLARWINDS_SERVICE_DESK_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields
    for name, config in SOLARWINDS_SERVICE_DESK_ENDPOINTS.items()
    if config.incremental_fields
}
