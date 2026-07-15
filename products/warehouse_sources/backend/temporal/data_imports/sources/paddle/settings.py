from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.constants import (
    ADJUSTMENT_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    DISCOUNT_RESOURCE_NAME,
    PRICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
    TRANSACTION_RESOURCE_NAME,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = [
    CUSTOMER_RESOURCE_NAME,
    DISCOUNT_RESOURCE_NAME,
    PRICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
    TRANSACTION_RESOURCE_NAME,
    ADJUSTMENT_RESOURCE_NAME,
]

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    TRANSACTION_RESOURCE_NAME: [
        {
            "label": "billed_at",
            "type": IncrementalFieldType.DateTime,
            "field": "billed_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}

# Partition key for every endpoint. `created_at` is set once and never changes on any Paddle
# entity, in both list-API and webhook payloads. Deliberately decoupled from the transactions
# incremental cursor (`billed_at`), which is null until a transaction is billed — null partition
# values all collapse into the partition layer's fallback bucket.
PARTITION_FIELD = "created_at"

# Webhook event types per resource. The flat list below is subscribed regardless of which tables
# are selected, so the notification destination self-heals as tables are enabled later.
RESOURCE_TO_PADDLE_EVENTS: dict[str, list[str]] = {
    TRANSACTION_RESOURCE_NAME: [
        "transaction.billed",
        "transaction.canceled",
        "transaction.completed",
        "transaction.created",
        "transaction.paid",
        "transaction.past_due",
        "transaction.payment_failed",
        "transaction.ready",
        "transaction.revised",
        "transaction.updated",
    ],
    SUBSCRIPTION_RESOURCE_NAME: [
        "subscription.activated",
        "subscription.canceled",
        "subscription.created",
        "subscription.imported",
        "subscription.past_due",
        "subscription.paused",
        "subscription.resumed",
        "subscription.trialing",
        "subscription.updated",
    ],
    CUSTOMER_RESOURCE_NAME: [
        "customer.created",
        "customer.imported",
        "customer.updated",
    ],
    PRODUCT_RESOURCE_NAME: [
        "product.created",
        "product.imported",
        "product.updated",
    ],
    PRICE_RESOURCE_NAME: [
        "price.created",
        "price.imported",
        "price.updated",
    ],
    DISCOUNT_RESOURCE_NAME: [
        "discount.created",
        "discount.imported",
        "discount.updated",
    ],
    ADJUSTMENT_RESOURCE_NAME: [
        "adjustment.created",
        "adjustment.updated",
    ],
}

PADDLE_WEBHOOK_EVENTS: list[str] = sorted({event for events in RESOURCE_TO_PADDLE_EVENTS.values() for event in events})
