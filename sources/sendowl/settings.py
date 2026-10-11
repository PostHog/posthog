from dataclasses import dataclass, field


@dataclass
class SendowlEndpointConfig:
    name: str
    path: str
    # SendOwl wraps every list item in a single-key object, e.g. `/api/v1/products` returns
    # `[{"product": {...}}, ...]`. `wrapper_key` names that key so `_fetch_page` can unwrap it.
    wrapper_key: str
    # SendOwl object IDs are unique per account, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# SendOwl list endpoints. All are full-refresh only. Resources are versioned per path: products,
# subscriptions and discount codes live under `/api/v1`, while orders use `/api/v1_3`.
SENDOWL_ENDPOINTS: dict[str, SendowlEndpointConfig] = {
    "products": SendowlEndpointConfig(name="products", path="/api/v1/products", wrapper_key="product"),
    "orders": SendowlEndpointConfig(name="orders", path="/api/v1_3/orders", wrapper_key="order"),
    "subscriptions": SendowlEndpointConfig(
        name="subscriptions", path="/api/v1/subscriptions", wrapper_key="subscription"
    ),
    "discount_codes": SendowlEndpointConfig(
        name="discount_codes", path="/api/v1/discount_codes", wrapper_key="discount_code"
    ),
}

ENDPOINTS = tuple(SENDOWL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list] = {}
