from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Veeqo defaults to tiny pages (12 on most endpoints, 10 on warehouses), so the page
# size is always set explicitly. `/products` documents a maximum of 100; the other
# endpoints document no maximum, so 100 is used everywhere for consistency.
DEFAULT_PAGE_SIZE = 100


@dataclass  # nosemgrep: prefer-frozen-dataclasses -- pre-existing; new field shifts the backlog finding into diff
class VeeqoEndpointConfig:
    """Declarative metadata for a single Veeqo list endpoint.

    `path` is appended to the API base URL. `partition_key` must be a STABLE field
    (`created_at`) so partitions are never rewritten — never `updated_at`; endpoints
    whose list response doesn't document a `created_at` column leave it unset.

    `incremental_fields` is the menu of advertised cursor options; the user's actual
    choice arrives via `inputs.incremental_field`. It is only populated for endpoints
    where Veeqo documents server-side filters (`updated_at_min` / `created_at_min` /
    `since_id`). Endpoints without a documented server-side filter ship full-refresh.
    """

    name: str
    path: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_key: Optional[str] = None
    # Static query params sent on every request (e.g. purchase_orders' show_complete).
    extra_params: dict[str, Any] = field(default_factory=dict)
    page_size: int = DEFAULT_PAGE_SIZE
    # True for endpoints that document no pagination params: the whole list arrives in
    # one response, so a page-number paginator would refetch the same full list forever
    # once it holds page_size or more rows.
    single_page: bool = False
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Veeqo has no list endpoints for returns, stock entries, shipments or bundles. Tables
    # set to True explode rows that `path` already embeds in each record, so they cost no
    # extra request.
    nested: bool = False
    # Tables that need one request per parent-derived id.
    fanout: Optional[DependentEndpointConfig] = None
    default_incremental_field: Optional[str] = None

    @property
    def supports_incremental(self) -> bool:
        return bool(self.incremental_fields)


def _timestamp_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


def _id_field() -> IncrementalField:
    return {
        "label": "id",
        "type": IncrementalFieldType.Integer,
        "field": "id",
        "field_type": IncrementalFieldType.Integer,
    }


# Orders and products document all three server-side filters: `updated_at_min`,
# `created_at_min`, and `since_id`. `updated_at` is the better default (catches
# mutations); `created_at` and `id` suit append-only consumers.
_FULL_INCREMENTAL_MENU = [_timestamp_field("updated_at"), _timestamp_field("created_at"), _id_field()]


VEEQO_ENDPOINTS: dict[str, VeeqoEndpointConfig] = {
    "orders": VeeqoEndpointConfig(
        name="orders",
        path="/orders",
        incremental_fields=_FULL_INCREMENTAL_MENU,
        partition_key="created_at",
    ),
    "products": VeeqoEndpointConfig(
        name="products",
        path="/products",
        incremental_fields=_FULL_INCREMENTAL_MENU,
        partition_key="created_at",
    ),
    # `/customers` only documents page/page_size/query/customer_type — no timestamp
    # or since_id filter, so full-refresh only.
    "customers": VeeqoEndpointConfig(
        name="customers",
        path="/customers",
    ),
    # `/purchase_orders` hides completed POs by default; show_complete=true includes
    # them so the warehouse table reflects the full history.
    "purchase_orders": VeeqoEndpointConfig(
        name="purchase_orders",
        path="/purchase_orders",
        partition_key="created_at",
        extra_params={"show_complete": "true"},
    ),
    "suppliers": VeeqoEndpointConfig(
        name="suppliers",
        path="/suppliers",
    ),
    "warehouses": VeeqoEndpointConfig(
        name="warehouses",
        path="/warehouses",
    ),
    # Veeqo calls stores "channels" in the API.
    "stores": VeeqoEndpointConfig(
        name="stores",
        path="/channels",
    ),
    # `/tags` documents no pagination params at all, so it's fetched as a single page —
    # paginating an endpoint that ignores `page` would refetch the same full list forever.
    "tags": VeeqoEndpointConfig(
        name="tags",
        path="/tags",
        single_page=True,
    ),
    "delivery_methods": VeeqoEndpointConfig(
        name="delivery_methods",
        path="/delivery_methods",
        partition_key="created_at",
    ),
    # Returns are embedded in each order (`returns`). `/orders/{id}/returns` documents a
    # required `sellable_id` query param, so a per-order request can't list them all.
    "returns": VeeqoEndpointConfig(
        name="returns",
        path="/orders",
        partition_key="created_at",
        primary_keys=["order_id", "id"],
        nested=True,
    ),
    # Each product embeds its sellables, and each sellable embeds its per-warehouse stock
    # entries — the same records `/sellables/{id}/warehouses/{id}/stock_entry` returns one
    # at a time.
    "stock_entries": VeeqoEndpointConfig(
        name="stock_entries",
        path="/products",
        primary_keys=["sellable_id", "warehouse_id"],
        nested=True,
    ),
    # Shipments are embedded in each order's allocations; Veeqo returns their events from a
    # per-shipment endpoint only.
    "shipment_tracking_events": VeeqoEndpointConfig(
        name="shipment_tracking_events",
        path="/shipping/tracking_events/{shipment_id}",
        primary_keys=["shipment_id", "timestamp", "status"],
        fanout=DependentEndpointConfig(
            parent_name="orders",
            resolve_param="shipment_id",
            resolve_field="shipment_id",
            include_from_parent=["shipment_id", "order_id"],
            parent_field_renames={"shipment_id": "shipment_id", "order_id": "order_id"},
            parent_params={"page_size": DEFAULT_PAGE_SIZE},
            # A shipment deleted between the orders listing and this request 404s.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    # Bundles ("kits") appear as sellables of type `Kit` on their product; `/kits/{id}`
    # returns the bundle with its `contents`.
    "bundle_contents": VeeqoEndpointConfig(
        name="bundle_contents",
        path="/kits/{kit_id}",
        primary_keys=["kit_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="products",
            resolve_param="kit_id",
            resolve_field="kit_id",
            include_from_parent=["kit_id", "product_id"],
            parent_field_renames={"kit_id": "kit_id", "product_id": "product_id"},
            parent_params={"page_size": DEFAULT_PAGE_SIZE},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
}

ENDPOINTS = tuple(VEEQO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in VEEQO_ENDPOINTS.items() if config.supports_incremental
}
