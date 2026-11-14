from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.sources.sdk import DependentEndpointConfig

# SendOwl caps `per_page` at 50 (default 10); the largest page minimises round trips while
# staying under the documented ~1 request/second advisory.
PER_PAGE = 50


@dataclass(frozen=True)
class SendowlEndpointConfig:
    name: str
    path: str
    # SendOwl wraps every list item in a single-key object, e.g. `/api/v1/products` returns
    # `[{"product": {...}}, ...]`. `wrapper_key` names that key so `_fetch_page` can unwrap it.
    wrapper_key: str
    # SendOwl object IDs are unique per account, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    fanout: Optional[DependentEndpointConfig] = None
    page_size: int = PER_PAGE
    incremental_fields: list[Any] = field(default_factory=list)
    default_incremental_field: Optional[str] = None


# SendOwl list endpoints, all full refresh. Orders use `/api/v1_3` and the rest use `/api/v1`.
# The API paths still call bundles packages.
SENDOWL_ENDPOINTS: dict[str, SendowlEndpointConfig] = {
    "products": SendowlEndpointConfig(name="products", path="/api/v1/products", wrapper_key="product"),
    "bundles": SendowlEndpointConfig(name="bundles", path="/api/v1/packages", wrapper_key="package"),
    "orders": SendowlEndpointConfig(name="orders", path="/api/v1_3/orders", wrapper_key="order"),
    "subscriptions": SendowlEndpointConfig(
        name="subscriptions", path="/api/v1/subscriptions", wrapper_key="subscription"
    ),
    "discount_codes": SendowlEndpointConfig(
        name="discount_codes", path="/api/v1/discount_codes", wrapper_key="discount_code"
    ),
    # The per-product list also holds keys not yet issued to an order, so the per-order list
    # (a subset) is not synced.
    "licenses": SendowlEndpointConfig(
        name="licenses",
        path="/api/v1/products/{product_id}/licenses",
        wrapper_key="license",
        fanout=DependentEndpointConfig(
            parent_name="products",
            resolve_param="product_id",
            resolve_field="id",
            include_from_parent=[],
        ),
    ),
}

ENDPOINTS = tuple(SENDOWL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list] = {}
