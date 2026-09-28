from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Every Fleetio index endpoint caps `per_page` at 100 (default 50), so always request the max.
PER_PAGE = 100


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


# Mutable by choice, not oversight: instances flow into `build_dependent_resource`'s
# `endpoint_configs: Mapping[str, FanoutEndpointLike]`, and mypy treats a frozen dataclass's
# fields as read-only, which is incompatible with that Protocol's plain (read-write) attributes.
@dataclass(frozen=False)
class FleetioEndpointConfig:
    name: str
    path: str
    # The resource's API generation, which versions up to 2024-06-30 carry as a path segment
    # (`/api/v1/vehicles`, `/api/v2/service_entries/...`). 2025-05-05 dropped those segments, so it
    # ignores this. Fleetio moved several resources to v2 over time, so this is per resource.
    path_version: str = "v1"
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: list(_DEFAULT_INCREMENTAL_FIELDS))
    # Partition by a stable field (created_at), never updated_at, so partitions don't rewrite each sync.
    partition_key: str | None = "created_at"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    # Set for a resource Fleetio only lists under a parent record, never account-wide.
    fanout: DependentEndpointConfig | None = None
    # Cursor field the fan-out helper binds to a server-side filter. Only read for a fan-out child
    # that merges, so it stays None for a child whose list action has no time filter.
    default_incremental_field: str | None = None
    # Page size the fan-out helper requests for this resource's list action.
    page_size: int = PER_PAGE


# Core data streams a Fleetio user will actually want, cross-referenced against the dltHub Fleetio
# source and the common Airbyte/Fivetran fleet-management stream list. Every entry exposes `id`,
# `created_at` and `updated_at`. `path_version` records the generation the 2024-06-30 docs serve the
# resource under, since Fleetio removed the v1 paths of the resources it moved to v2.
FLEETIO_ENDPOINTS: dict[str, FleetioEndpointConfig] = {
    "vehicles": FleetioEndpointConfig(name="vehicles", path="/vehicles"),
    "contacts": FleetioEndpointConfig(name="contacts", path="/contacts", path_version="v2"),
    "fuel_entries": FleetioEndpointConfig(name="fuel_entries", path="/fuel_entries"),
    "meter_entries": FleetioEndpointConfig(name="meter_entries", path="/meter_entries"),
    "service_entries": FleetioEndpointConfig(name="service_entries", path="/service_entries", path_version="v2"),
    "work_orders": FleetioEndpointConfig(name="work_orders", path="/work_orders", path_version="v2"),
    "issues": FleetioEndpointConfig(name="issues", path="/issues", path_version="v2"),
    "parts": FleetioEndpointConfig(name="parts", path="/parts"),
    "vehicle_assignments": FleetioEndpointConfig(name="vehicle_assignments", path="/vehicle_assignments"),
    "expense_entries": FleetioEndpointConfig(name="expense_entries", path="/expense_entries"),
    "expense_entry_types": FleetioEndpointConfig(name="expense_entry_types", path="/expense_entry_types"),
    "purchase_orders": FleetioEndpointConfig(name="purchase_orders", path="/purchase_orders"),
    # Lookup tables resolving the ids carried on the transactional rows above.
    "vehicle_statuses": FleetioEndpointConfig(name="vehicle_statuses", path="/vehicle_statuses"),
    "work_order_statuses": FleetioEndpointConfig(name="work_order_statuses", path="/work_order_statuses"),
    "vehicle_types": FleetioEndpointConfig(name="vehicle_types", path="/vehicle_types"),
    "service_tasks": FleetioEndpointConfig(name="service_tasks", path="/service_tasks"),
    "vendors": FleetioEndpointConfig(name="vendors", path="/vendors"),
    # Line items are only listed per service entry, so fan out over the service entries endpoint.
    # The list action takes no `filter` param — only `sort[id]` — so this is full refresh only.
    "service_entry_line_items": FleetioEndpointConfig(
        name="service_entry_line_items",
        path="/service_entries/{service_entry_id}/service_entry_line_items",
        path_version="v2",
        incremental_fields=[],
        primary_keys=["service_entry_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="service_entries",
            resolve_param="service_entry_id",
            resolve_field="id",
            # The line item carries `service_entry_id` itself, but the field is not required by the
            # schema, so take it from the parent row to keep the composite primary key populated.
            include_from_parent=["id"],
            parent_field_renames={"id": "service_entry_id"},
            parent_params={"sort[created_at]": "asc"},
            child_params={"sort[id]": "asc"},
        ),
    ),
    # Line items are only listed per purchase order, and the path binds the order's `number`
    # rather than its id. The list action takes no `filter` param — only `sort[id]` — so this is
    # full refresh only.
    "purchase_order_line_items": FleetioEndpointConfig(
        name="purchase_order_line_items",
        path="/purchase_orders/{number}/purchase_order_line_items",
        incremental_fields=[],
        primary_keys=["purchase_order_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="purchase_orders",
            resolve_param="number",
            resolve_field="number",
            # The line item carries neither identifier of the order it belongs to, so take both
            # from the parent row: the id to populate the composite primary key and join back to
            # `purchase_orders`, the number because that is what the path and the Fleetio UI use.
            include_from_parent=["id", "number"],
            parent_field_renames={"id": "purchase_order_id", "number": "purchase_order_number"},
            parent_params={"sort[created_at]": "asc"},
            child_params={"sort[id]": "asc"},
        ),
    ),
}

ENDPOINTS = tuple(FLEETIO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FLEETIO_ENDPOINTS.items()
}
