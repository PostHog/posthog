from dataclasses import dataclass

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

API_BASE_URL = "https://api.razorpay.com"

# `count` is capped at 100 by the API (default 10).
PAGE_SIZE = 100


@dataclass(frozen=True)
class RazorpayEndpointConfig:
    name: str
    path: str
    # Whether the endpoint documents the standard `from`/`to` created_at window filters.
    # Endpoints without them sync as full refresh only.
    supports_created_filter: bool
    primary_key: str = "id"
    partition_key: str = "created_at"


ENDPOINT_CONFIGS: dict[str, RazorpayEndpointConfig] = {
    "Customers": RazorpayEndpointConfig(
        name="Customers",
        path="/v1/customers",
        supports_created_filter=True,
    ),
    # The disputes docs don't list `from`/`to` filters, so full refresh only. Disputes are
    # heavily mutable (status/phase transitions), so full refresh is also the safer sync mode.
    "Disputes": RazorpayEndpointConfig(
        name="Disputes",
        path="/v1/disputes",
        supports_created_filter=False,
    ),
    # The invoices docs list only type/payment_id/receipt/customer_id filters — no documented
    # `from`/`to` — so full refresh only.
    "Invoices": RazorpayEndpointConfig(
        name="Invoices",
        path="/v1/invoices",
        supports_created_filter=False,
    ),
    "Items": RazorpayEndpointConfig(
        name="Items",
        path="/v1/items",
        supports_created_filter=True,
    ),
    "Orders": RazorpayEndpointConfig(
        name="Orders",
        path="/v1/orders",
        supports_created_filter=True,
    ),
    "Payments": RazorpayEndpointConfig(
        name="Payments",
        path="/v1/payments",
        supports_created_filter=True,
    ),
    "Plans": RazorpayEndpointConfig(
        name="Plans",
        path="/v1/plans",
        supports_created_filter=True,
    ),
    "Refunds": RazorpayEndpointConfig(
        name="Refunds",
        path="/v1/refunds",
        supports_created_filter=True,
    ),
    "Settlements": RazorpayEndpointConfig(
        name="Settlements",
        path="/v1/settlements",
        supports_created_filter=True,
    ),
    "Subscriptions": RazorpayEndpointConfig(
        name="Subscriptions",
        path="/v1/subscriptions",
        supports_created_filter=True,
    ),
    # Smart Collect docs confirm count/skip pagination but not `from`/`to`, so full refresh only.
    "VirtualAccounts": RazorpayEndpointConfig(
        name="VirtualAccounts",
        path="/v1/virtual_accounts",
        supports_created_filter=False,
    ),
}

ENDPOINTS = tuple(ENDPOINT_CONFIGS.keys())

# Razorpay only filters on created_at (there is no updated-at filter), advertised as a DateTime
# cursor stored as a UNIX-seconds integer.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.Integer,
        }
    ]
    for name, config in ENDPOINT_CONFIGS.items()
    if config.supports_created_filter
}
