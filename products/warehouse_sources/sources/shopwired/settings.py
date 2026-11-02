from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# List endpoints accept a `count` of up to 100 (default 50); the largest page minimises round trips
# against ShopWired's leaky-bucket rate limit (burst 40, 2 requests/second sustained).
PAGE_SIZE = 100

# Orders are the only resource with a documented server-side created-date filter (`from`/`to` UNIX
# timestamps) and a date sort (`sort=date`/`date_desc`), so they are the only incremental endpoint.
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


@dataclass
class ShopWiredEndpointConfig:
    name: str
    path: str
    # ShopWired object IDs are integers, unique per resource across the whole account.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation timestamp used for datetime partitioning, when the resource exposes one.
    partition_key: Optional[str] = None
    # Query param value for `sort` guaranteeing a stable ascending order while paginating.
    # `None` keeps the API default (creation-date order).
    sort_param: Optional[str] = None
    # The order-statuses endpoint documents no pagination params, so it's fetched in one request.
    paginated: bool = True


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
}

ENDPOINTS = tuple(SHOPWIRED_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SHOPWIRED_ENDPOINTS.items() if config.incremental_fields
}
