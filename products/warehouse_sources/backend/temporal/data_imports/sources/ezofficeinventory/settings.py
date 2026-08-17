from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField

# Vendor API version labels. v1 is the legacy `*.api` interface (token header, page-number
# pagination); v2 is the GA `/api/v2/` REST interface (bearer token, next-URL pagination).
EZOFFICEINVENTORY_API_VERSION_V1 = "v1"
EZOFFICEINVENTORY_API_VERSION_V2 = "v2"


@dataclass
class EZOfficeInventoryEndpointConfig:
    name: str
    # Path relative to https://<subdomain>.ezofficeinventory.com (no leading slash).
    path: str
    # Top-level key in the JSON response that holds the list of records.
    data_selector: str
    # Some list endpoints wrap each record in a single-key object (e.g. groups returns
    # `{"groups": [{"group": {...}}]}`); set this to the inner key to unwrap it.
    unwrap_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation timestamp used for datetime partitioning. Never an `updated_at`-style
    # field — partitions must not rewrite on every sync. None disables partitioning.
    partition_key: Optional[str] = None
    # Extra static query params (e.g. the `status=checked_out` filter on /assets/filter.api).
    extra_params: dict[str, str] = field(default_factory=dict)
    should_sync_default: bool = True


# EZOfficeInventory exposes no general server-side `updated_after`/`created_after` cursor on its
# core listing endpoints, and its per-asset history endpoints only paginate (no server-side date
# filter — the date bound applied by other connectors is purely client-side). Every endpoint here
# is therefore full refresh; see SOURCES.md / the source docstring for the incremental-sync note.
EZOFFICEINVENTORY_ENDPOINTS: dict[str, EZOfficeInventoryEndpointConfig] = {
    "assets": EZOfficeInventoryEndpointConfig(
        name="assets",
        path="assets.api",
        data_selector="assets",
        primary_keys=["identifier"],
        partition_key="created_at",
    ),
    "inventories": EZOfficeInventoryEndpointConfig(
        name="inventories",
        path="inventory.api",
        data_selector="volatile_assets",
        primary_keys=["identifier"],
        partition_key="created_at",
    ),
    "asset_stocks": EZOfficeInventoryEndpointConfig(
        name="asset_stocks",
        path="stock_assets.api",
        data_selector="stock_assets",
        primary_keys=["identifier"],
        partition_key="created_at",
    ),
    "checked_out_assets": EZOfficeInventoryEndpointConfig(
        name="checked_out_assets",
        path="assets/filter.api",
        data_selector="assets",
        primary_keys=["identifier"],
        partition_key="created_at",
        extra_params={"status": "checked_out"},
    ),
    "members": EZOfficeInventoryEndpointConfig(
        name="members",
        path="members.api",
        data_selector="members",
        primary_keys=["id"],
        partition_key="created_at",
    ),
    "locations": EZOfficeInventoryEndpointConfig(
        name="locations",
        path="locations/get_line_item_locations.api",
        data_selector="locations",
        primary_keys=["id"],
        partition_key="created_at",
    ),
    "groups": EZOfficeInventoryEndpointConfig(
        name="groups",
        path="assets/classification_view.api",
        data_selector="groups",
        unwrap_key="group",
        primary_keys=["id"],
        partition_key="created_at",
    ),
    "subgroups": EZOfficeInventoryEndpointConfig(
        name="subgroups",
        path="groups/get_sub_groups.api",
        data_selector="sub_groups",
        primary_keys=["id"],
        partition_key="created_at",
    ),
    "vendors": EZOfficeInventoryEndpointConfig(
        name="vendors",
        path="assets/vendors.api",
        data_selector="vendors",
        unwrap_key="vendor",
        primary_keys=["id"],
        partition_key="created_at",
    ),
    "labels": EZOfficeInventoryEndpointConfig(
        name="labels",
        path="print_label_templates.api",
        data_selector="print_label_templates",
        primary_keys=["id"],
    ),
    "custom_fields": EZOfficeInventoryEndpointConfig(
        name="custom_fields",
        path="assets/custom_attributes.api",
        data_selector="custom_attributes",
        primary_keys=["id"],
    ),
    "purchase_orders": EZOfficeInventoryEndpointConfig(
        name="purchase_orders",
        path="purchase_orders.api",
        data_selector="purchase_orders",
        primary_keys=["id"],
        partition_key="created_at",
    ),
}

ENDPOINTS = tuple(EZOFFICEINVENTORY_ENDPOINTS.keys())

# v2 (`/api/v2/`) serves the core inventory resources as flat REST list endpoints. Paths and
# response envelopes differ from v1: records are no longer wrapped per row (no `unwrap_key`), the
# list key is renamed for some resources (inventory, stock assets), and vendors expose no
# `created_at`, so that table can't be datetime-partitioned under v2. The v1-only endpoints
# (`checked_out_assets`, `subgroups`, `labels`, `custom_fields`) have no flat v2 list equivalent
# and stay v1-only — pinned v1 sources keep serving them.
EZOFFICEINVENTORY_V2_ENDPOINTS: dict[str, EZOfficeInventoryEndpointConfig] = {
    "assets": EZOfficeInventoryEndpointConfig(
        name="assets",
        path="api/v2/assets",
        data_selector="assets",
        primary_keys=["identifier"],
        partition_key="created_at",
    ),
    "inventories": EZOfficeInventoryEndpointConfig(
        name="inventories",
        path="api/v2/inventory",
        data_selector="inventory",
        primary_keys=["identifier"],
        partition_key="created_at",
    ),
    "asset_stocks": EZOfficeInventoryEndpointConfig(
        name="asset_stocks",
        path="api/v2/stock_assets",
        data_selector="asset_stock",
        primary_keys=["identifier"],
        partition_key="created_at",
    ),
    "members": EZOfficeInventoryEndpointConfig(
        name="members",
        path="api/v2/members",
        data_selector="members",
        primary_keys=["id"],
        partition_key="created_at",
    ),
    "locations": EZOfficeInventoryEndpointConfig(
        name="locations",
        path="api/v2/locations",
        data_selector="locations",
        primary_keys=["id"],
        partition_key="created_at",
    ),
    "groups": EZOfficeInventoryEndpointConfig(
        name="groups",
        path="api/v2/groups",
        data_selector="groups",
        primary_keys=["id"],
        partition_key="created_at",
    ),
    "vendors": EZOfficeInventoryEndpointConfig(
        name="vendors",
        path="api/v2/vendors",
        data_selector="vendors",
        primary_keys=["id"],
    ),
    "purchase_orders": EZOfficeInventoryEndpointConfig(
        name="purchase_orders",
        path="api/v2/purchase_orders",
        data_selector="purchase_orders",
        primary_keys=["id"],
        partition_key="created_at",
    ),
}

V2_ENDPOINTS = tuple(EZOFFICEINVENTORY_V2_ENDPOINTS.keys())


def endpoints_for_version(api_version: str) -> dict[str, EZOfficeInventoryEndpointConfig]:
    if api_version == EZOFFICEINVENTORY_API_VERSION_V2:
        return EZOFFICEINVENTORY_V2_ENDPOINTS
    return EZOFFICEINVENTORY_ENDPOINTS


# Every endpoint is full refresh — no server-side timestamp filter is available.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
