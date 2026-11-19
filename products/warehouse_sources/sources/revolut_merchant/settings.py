from dataclasses import field

from products.warehouse_sources.sources.sdk import Endpoint, IncrementalField, SortMode, frozen

API_VERSION = "2026-08-17"
CREATED_DATE_PAGE_SIZE = 500
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
    parent_id_column: str | None = None
    created_date_pagination: bool = False
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
        parent_id_column="order_id",
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
    "subscription_cycles": RevolutMerchantEndpoint(
        endpoint={
            "path": "/subscriptions/{subscription_id}/cycles",
            "params": {
                "subscription_id": {"type": "resolve", "resource": "subscriptions", "field": "id"},
                "limit": 500,
            },
            "data_selector": "cycles",
            "data_selector_required": True,
            "paginator": {"type": "cursor", "cursor_path": "next_page_token", "cursor_param": "page_token"},
        },
        primary_keys=["subscription_id", "id"],
        partition_key="start_date",
        parent="subscriptions",
        parent_id_column="subscription_id",
    ),
    "subscription_usages": RevolutMerchantEndpoint(
        endpoint={
            "path": "/subscription-usages",
            "params": {"limit": 500},
            "data_selector": "subscription_usages",
            "data_selector_required": True,
            "paginator": {"type": "cursor", "cursor_path": "next_page_token", "cursor_param": "page_token"},
        },
    ),
    "payouts": RevolutMerchantEndpoint(
        endpoint={
            "path": "/payouts",
            "params": {"limit": CREATED_DATE_PAGE_SIZE},
            "data_selector": None,
            "data_selector_required": True,
        },
        created_date_pagination=True,
    ),
    "disputes": RevolutMerchantEndpoint(
        endpoint={
            "path": "/disputes",
            "params": {"limit": CREATED_DATE_PAGE_SIZE},
            "data_selector": None,
            "data_selector_required": True,
        },
        created_date_pagination=True,
    ),
}

INCREMENTAL_FIELDS = {name: endpoint.incremental_fields for name, endpoint in ENDPOINTS.items()}
