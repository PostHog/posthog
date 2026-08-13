from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Veeqo defaults to tiny pages (12 on most endpoints, 10 on warehouses), so the page
# size is always set explicitly. `/products` documents a maximum of 100; the other
# endpoints document no maximum, so 100 is used everywhere for consistency.
DEFAULT_PAGE_SIZE = 100


@dataclass
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
}

ENDPOINTS = tuple(VEEQO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in VEEQO_ENDPOINTS.items() if config.supports_incremental
}
