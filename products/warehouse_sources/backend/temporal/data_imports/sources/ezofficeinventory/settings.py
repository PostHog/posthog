from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
from products.warehouse_sources.backend.types import IncrementalField

# v2 list endpoints cap page size at 100. Only the fan-out parents send it, to keep the number of
# requests down against the account's ~60 req/min fair-use limit.
PAGE_SIZE = 100

# Vendor API version labels. v1 is the legacy `*.api` interface (token header, page-number
# pagination); v2 is the GA `/api/v2/` REST interface (bearer token, next-URL pagination).
EZOFFICEINVENTORY_API_VERSION_V1 = "v1"
EZOFFICEINVENTORY_API_VERSION_V2 = "v2"


# frozen=False: the shared FanoutEndpointLike protocol is satisfied either way, but the config
# stays mutable to match the other endpoint-catalog dataclasses in this tree.
@dataclass(frozen=False)
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
    # When set, the endpoint is a per-parent sub-resource fetched once per row of another
    # endpoint rather than a flat list.
    fanout: Optional[DependentEndpointConfig] = None
    # The three below exist so the config satisfies the shared FanoutEndpointLike protocol.
    # Nothing on this source reads them: page sizes are set per fan-out through
    # `parent_params`, and every EZOfficeInventory table is full refresh.
    page_size: int = PAGE_SIZE
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None


# A parent row retired or deleted between the parent listing and its child fetch answers 404.
# Ignoring it keeps the fan-out going instead of failing the whole table.
_PARENT_GONE: list[ResponseAction] = [{"status_code": 404, "action": "ignore"}]

# The history sub-resources are keyed on the record id (`id`), not the user-facing identification
# number, so the parent id is what binds the child path. It is also injected onto every child row,
# because a history row carries no reference back to the item or member it belongs to.
_ASSET_HISTORY_FANOUT = DependentEndpointConfig(
    parent_name="assets",
    resolve_param="asset_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "asset_id"},
    parent_params={"per_page": PAGE_SIZE},
    child_response_actions=_PARENT_GONE,
)

_MEMBER_STOCK_HISTORY_FANOUT = DependentEndpointConfig(
    parent_name="members",
    resolve_param="member_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "member_id"},
    parent_params={"per_page": PAGE_SIZE},
    child_response_actions=_PARENT_GONE,
)


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
    "teams": EZOfficeInventoryEndpointConfig(
        name="teams",
        path="teams.api",
        data_selector="teams",
        primary_keys=["id"],
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
#
# Work orders and the two history tables are v2-only. v1 reaches the same records through
# `tasks.api`, `assets/<id>/history_paginate.api` and `members/<id>/checkin_checkout_history*.api`,
# but the v1 docs give no response envelope for any of them, and a guessed `data_selector` yields
# an empty table rather than an error. The v2 OpenAPI spec names all three, so they are wired
# there only.
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
    "teams": EZOfficeInventoryEndpointConfig(
        name="teams",
        path="api/v2/teams",
        data_selector="teams",
        primary_keys=["id"],
    ),
    "work_orders": EZOfficeInventoryEndpointConfig(
        name="work_orders",
        path="api/v2/work_orders",
        data_selector="work_orders",
        primary_keys=["id"],
        partition_key="created_at",
    ),
    "asset_checkout_history": EZOfficeInventoryEndpointConfig(
        name="asset_checkout_history",
        path="api/v2/assets/{asset_id}/history",
        data_selector="histories",
        # The history id is only documented as unique within its asset, so the parent id is part
        # of the key. It stays correct if the id turns out to be unique account-wide.
        primary_keys=["asset_id", "id"],
        partition_key="created_at",
        fanout=_ASSET_HISTORY_FANOUT,
        # One request per asset, so it is opt-in rather than on by default.
        should_sync_default=False,
    ),
    "member_stock_histories": EZOfficeInventoryEndpointConfig(
        name="member_stock_histories",
        path="api/v2/members/{member_id}/stock_histories",
        data_selector="stock_histories",
        primary_keys=["member_id", "id"],
        partition_key="created_at",
        fanout=_MEMBER_STOCK_HISTORY_FANOUT,
        # One request per member, so it is opt-in rather than on by default.
        should_sync_default=False,
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
