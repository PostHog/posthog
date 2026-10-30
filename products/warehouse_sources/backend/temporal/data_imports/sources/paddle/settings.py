from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.constants import (
    ADJUSTMENT_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    DISCOUNT_RESOURCE_NAME,
    EXPLORE_METRICS_RESOURCE_NAME,
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
    EXPLORE_METRICS_RESOURCE_NAME,
]

# Explore metrics need the separate `metrics.read` permission, so the connection check skips them
# and a key without it can still sync the other tables.
CREDENTIAL_CHECK_ENDPOINTS = [endpoint for endpoint in ENDPOINTS if endpoint != EXPLORE_METRICS_RESOURCE_NAME]

# Paddle refreshes Explore data on a 24-hour cycle, so recent buckets can change after a sync.
EXPLORE_METRICS_LOOKBACK_SECONDS = 60 * 60 * 24 * 3

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    TRANSACTION_RESOURCE_NAME: [
        {
            "label": "billed_at",
            "type": IncrementalFieldType.DateTime,
            "field": "billed_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    EXPLORE_METRICS_RESOURCE_NAME: [
        {
            "label": "timestamp",
            "type": IncrementalFieldType.DateTime,
            "field": "timestamp",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}
