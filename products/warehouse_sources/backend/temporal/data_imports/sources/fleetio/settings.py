from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


# Every core Fleetio index endpoint exposes `updated_at` (server-managed, monotonic on change) and
# `created_at` (stable). We offer both as incremental cursors and default the partition to `created_at`
# so partitions never rewrite.
_DEFAULT_INCREMENTAL_FIELDS: list[IncrementalField] = [_datetime_field("updated_at"), _datetime_field("created_at")]


@dataclass
class FleetioEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: list(_DEFAULT_INCREMENTAL_FIELDS))
    # Partition by a stable field (created_at), never updated_at, so partitions don't rewrite each sync.
    partition_key: str | None = "created_at"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True


# Core data streams a Fleetio user will actually want, cross-referenced against the dltHub Fleetio
# source and the common Airbyte/Fivetran fleet-management stream list. All are top-level index
# endpoints under https://secure.fleetio.com/api/v1 with `id`, `created_at`, and `updated_at`.
FLEETIO_ENDPOINTS: dict[str, FleetioEndpointConfig] = {
    "vehicles": FleetioEndpointConfig(name="vehicles", path="/vehicles"),
    "contacts": FleetioEndpointConfig(name="contacts", path="/contacts"),
    "fuel_entries": FleetioEndpointConfig(name="fuel_entries", path="/fuel_entries"),
    "meter_entries": FleetioEndpointConfig(name="meter_entries", path="/meter_entries"),
    "service_entries": FleetioEndpointConfig(name="service_entries", path="/service_entries"),
    "work_orders": FleetioEndpointConfig(name="work_orders", path="/work_orders"),
    "issues": FleetioEndpointConfig(name="issues", path="/issues"),
    "parts": FleetioEndpointConfig(name="parts", path="/parts"),
    "vehicle_assignments": FleetioEndpointConfig(name="vehicle_assignments", path="/vehicle_assignments"),
}

ENDPOINTS = tuple(FLEETIO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FLEETIO_ENDPOINTS.items()
}
