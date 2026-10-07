from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField

API_VERSION = "2026-08-17"
BASE_URLS = {
    "production": "https://merchant.revolut.com/api",
    "sandbox": "https://sandbox-merchant.revolut.com/api",
}


@frozen
class RevolutMerchantEndpoint:
    endpoint: Endpoint
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: str = "created_at"
    sort_mode: SortMode | None = None
    parent: str | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)


# Creation filters miss later payment, profile, and subscription changes, so imports use full refresh.
ENDPOINTS: dict[str, RevolutMerchantEndpoint] = {
    "orders": RevolutMerchantEndpoint(
        endpoint={
            # The replacement /orders specification omits a continuation mechanism.
            "path": "/1.0/orders",
            "params": {"limit": 1000},
            "data_selector": None,
            "data_selector_required": True,
            "paginator": {"type": "cursor", "cursor_path": "$[-1].created_at", "cursor_param": "created_before"},
        },
        sort_mode="desc",
    ),
    "payments": RevolutMerchantEndpoint(
        endpoint={
            "path": "/orders/{order_id}/payments",
            "params": {"order_id": {"type": "resolve", "resource": "orders", "field": "id"}},
            "data_selector": None,
            "data_selector_required": True,
            "paginator": "single_page",
        },
        primary_keys=["order_id", "id"],
        parent="orders",
    ),
    "customers": RevolutMerchantEndpoint(
        endpoint={
            "path": "/customers",
            "params": {"limit": 500},
            "data_selector": "customers",
            "data_selector_required": True,
            "paginator": {"type": "cursor", "cursor_path": "next_page_token", "cursor_param": "page_token"},
        },
    ),
    "subscriptions": RevolutMerchantEndpoint(
        endpoint={
            "path": "/subscriptions",
            "params": {"limit": 500},
            "data_selector": "subscriptions",
            "data_selector_required": True,
            "paginator": {"type": "cursor", "cursor_path": "next_page_token", "cursor_param": "page_token"},
        },
    ),
    "subscription_plans": RevolutMerchantEndpoint(
        endpoint={
            "path": "/subscription-plans",
            "params": {"limit": 500},
            "data_selector": "subscription_plans",
            "data_selector_required": True,
            "paginator": {"type": "cursor", "cursor_path": "next_page_token", "cursor_param": "page_token"},
        },
    ),
}

INCREMENTAL_FIELDS = {name: endpoint.incremental_fields for name, endpoint in ENDPOINTS.items()}
