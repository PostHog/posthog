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

# Webhook event types per resource. Trimmed to the minimal set that still delivers every state we
# care about: `<entity>.updated` fires on every state transition, so the convenience/status events
# (billed, paid, activated, canceled, …) are redundant. We keep `created` (a transaction can be
# created already billed) and `imported` (bulk imports don't fire `updated`). `transaction.payment_failed`
# is kept because it does not change transaction state and so has no companion `updated`. The flat
# list is subscribed regardless of which tables are selected, so the destination self-heals as tables
# are enabled later.
RESOURCE_TO_PADDLE_EVENTS: dict[str, list[str]] = {
    TRANSACTION_RESOURCE_NAME: [
        "transaction.created",
        "transaction.payment_failed",
        "transaction.updated",
    ],
    SUBSCRIPTION_RESOURCE_NAME: [
        "subscription.created",
        "subscription.imported",
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
