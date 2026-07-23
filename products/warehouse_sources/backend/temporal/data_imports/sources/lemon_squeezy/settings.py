from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.lemonsqueezy.com"

# Lemon Squeezy caps list pages at 100 items (default is 10).
PAGE_SIZE = 100

# JSON:API headers Lemon Squeezy requires on every request.
JSON_API_HEADERS = {
    "Accept": "application/vnd.api+json",
    "Content-Type": "application/vnd.api+json",
}


@dataclass
class LemonSqueezyEndpointConfig:
    path: str
    # JSON:API resource type carried in `data[].type` — also the routing key for webhook
    # deliveries of this resource.
    json_api_type: str
    # Set only on append-mostly endpoints: list endpoints return rows created_at-descending
    # with no server-side timestamp filter, so incremental sync is a stop-early cursor —
    # pagination halts once an entire page predates the watermark. Mutable resources
    # (subscriptions, customers, license keys) are full refresh (+ webhooks where offered)
    # because a created_at cursor would never re-surface in-place updates.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Every Lemon Squeezy resource carries a stable `created_at`; used for datetime partitioning.
    partition_key: str = "created_at"


LEMON_SQUEEZY_ENDPOINTS: dict[str, LemonSqueezyEndpointConfig] = {
    "stores": LemonSqueezyEndpointConfig(path="/v1/stores", json_api_type="stores"),
    "customers": LemonSqueezyEndpointConfig(path="/v1/customers", json_api_type="customers"),
    "products": LemonSqueezyEndpointConfig(path="/v1/products", json_api_type="products"),
    "variants": LemonSqueezyEndpointConfig(path="/v1/variants", json_api_type="variants"),
    "prices": LemonSqueezyEndpointConfig(path="/v1/prices", json_api_type="prices"),
    "files": LemonSqueezyEndpointConfig(path="/v1/files", json_api_type="files"),
    "orders": LemonSqueezyEndpointConfig(
        path="/v1/orders",
        json_api_type="orders",
        incremental_fields=[incremental_field("created_at")],
    ),
    "order_items": LemonSqueezyEndpointConfig(
        path="/v1/order-items",
        json_api_type="order-items",
        incremental_fields=[incremental_field("created_at")],
    ),
    "subscriptions": LemonSqueezyEndpointConfig(path="/v1/subscriptions", json_api_type="subscriptions"),
    "subscription_invoices": LemonSqueezyEndpointConfig(
        path="/v1/subscription-invoices",
        json_api_type="subscription-invoices",
        incremental_fields=[incremental_field("created_at")],
    ),
    "subscription_items": LemonSqueezyEndpointConfig(path="/v1/subscription-items", json_api_type="subscription-items"),
    "usage_records": LemonSqueezyEndpointConfig(
        path="/v1/usage-records",
        json_api_type="usage-records",
        incremental_fields=[incremental_field("created_at")],
    ),
    "discounts": LemonSqueezyEndpointConfig(path="/v1/discounts", json_api_type="discounts"),
    "discount_redemptions": LemonSqueezyEndpointConfig(
        path="/v1/discount-redemptions",
        json_api_type="discount-redemptions",
        incremental_fields=[incremental_field("created_at")],
    ),
    "license_keys": LemonSqueezyEndpointConfig(path="/v1/license-keys", json_api_type="license-keys"),
    "license_key_instances": LemonSqueezyEndpointConfig(
        path="/v1/license-key-instances", json_api_type="license-key-instances"
    ),
    "checkouts": LemonSqueezyEndpointConfig(path="/v1/checkouts", json_api_type="checkouts"),
}

ENDPOINTS = tuple(LEMON_SQUEEZY_ENDPOINTS.keys())

INCREMENTAL_ENDPOINTS = tuple(name for name, config in LEMON_SQUEEZY_ENDPOINTS.items() if config.incremental_fields)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LEMON_SQUEEZY_ENDPOINTS.items() if config.incremental_fields
}

# Webhook events per schema. Every delivery carries the full resource in JSON:API shape,
# so webhook rows merge onto the same tables the pull API fills.
SCHEMA_TO_WEBHOOK_EVENTS: dict[str, list[str]] = {
    "orders": ["order_created", "order_refunded"],
    "subscriptions": [
        "subscription_created",
        "subscription_updated",
        "subscription_cancelled",
        "subscription_resumed",
        "subscription_expired",
        "subscription_paused",
        "subscription_unpaused",
        "subscription_plan_changed",
    ],
    "subscription_invoices": [
        "subscription_payment_success",
        "subscription_payment_failed",
        "subscription_payment_recovered",
        "subscription_payment_refunded",
    ],
    "license_keys": ["license_key_created", "license_key_updated"],
}

WEBHOOK_SCHEMA_NAMES = tuple(SCHEMA_TO_WEBHOOK_EVENTS.keys())

ALL_WEBHOOK_EVENTS = sorted({event for events in SCHEMA_TO_WEBHOOK_EVENTS.values() for event in events})

# Schema name -> JSON:API resource type: the key incoming webhook deliveries are routed by
# (the hog template looks up `request.body.data.type` in `schema_mapping`).
RESOURCE_TO_JSON_API_TYPE: dict[str, str] = {
    name: LEMON_SQUEEZY_ENDPOINTS[name].json_api_type for name in WEBHOOK_SCHEMA_NAMES
}
