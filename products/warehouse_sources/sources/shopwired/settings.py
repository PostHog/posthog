from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, IncrementalFieldType

# List endpoints accept a `count` of up to 100 (default 50); the largest page minimises round trips
# against ShopWired's leaky-bucket rate limit (burst 40, 2 requests/second sustained).
PAGE_SIZE = 100

# Orders and incomplete orders support a creation-date filter and ascending date sort.
# `created` is stable (an order's creation date never changes), making it safe for both the
# incremental cursor and datetime partitioning.
_CREATED_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "created",
        "type": IncrementalFieldType.DateTime,
        "field": "created",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass(frozen=False)
class ShopWiredEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation timestamp used for datetime partitioning, when the resource exposes one.
    partition_key: Optional[str] = None
    # Query param value for `sort` guaranteeing a stable ascending order while paginating.
    # `None` keeps the API default (creation-date order).
    sort_param: Optional[str] = None
    # The order-statuses endpoint documents no pagination params, so it's fetched in one request.
    paginated: bool = True
    fanout: DependentEndpointConfig | None = None
    page_size: int = PAGE_SIZE
    default_incremental_field: str | None = None


SHOPWIRED_ENDPOINTS: dict[str, ShopWiredEndpointConfig] = {
    "products": ShopWiredEndpointConfig(name="products", path="/products"),
    "categories": ShopWiredEndpointConfig(name="categories", path="/categories"),
    "brands": ShopWiredEndpointConfig(name="brands", path="/brands"),
    "tags": ShopWiredEndpointConfig(name="tags", path="/tags"),
    "customers": ShopWiredEndpointConfig(name="customers", path="/customers"),
    "orders": ShopWiredEndpointConfig(
        name="orders",
        path="/orders",
        incremental_fields=_CREATED_INCREMENTAL,
        partition_key="created",
        # Ascending creation-date sort keeps the pipeline's incremental watermark
        # (`sort_mode="asc"`) advancing correctly while paginating.
        sort_param="date",
    ),
    "order_statuses": ShopWiredEndpointConfig(name="order_statuses", path="/order-statuses", paginated=False),
    "vouchers": ShopWiredEndpointConfig(name="vouchers", path="/vouchers"),
    "transactions": ShopWiredEndpointConfig(
        name="transactions", path="/shopwired-payments/transactions", sort_param="created_asc"
    ),
    "product_variations": ShopWiredEndpointConfig(
        name="product_variations",
        path="/products/{product_id}/variations",
        primary_keys=["product_id", "id"],
        paginated=False,
        fanout=DependentEndpointConfig(
            parent_name="products",
            resolve_param="product_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "product_id"},
        ),
    ),
    "incomplete_orders": ShopWiredEndpointConfig(
        name="incomplete_orders",
        path="/incomplete-orders",
        incremental_fields=_CREATED_INCREMENTAL,
        partition_key="created",
        sort_param="date",
    ),
    "payouts": ShopWiredEndpointConfig(name="payouts", path="/shopwired-payments/payouts", sort_param="created_asc"),
}

ENDPOINTS = tuple(SHOPWIRED_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SHOPWIRED_ENDPOINTS.items() if config.incremental_fields
}
