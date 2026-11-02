from products.warehouse_sources.backend.temporal.data_imports.sources.polar.constants import (
    BENEFIT_RESOURCE_NAME,
    CHECKOUT_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    ORDER_RESOURCE_NAME,
    ORGANIZATION_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    REFUND_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
)

ENDPOINTS = [
    CUSTOMER_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    ORDER_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
    REFUND_RESOURCE_NAME,
    CHECKOUT_RESOURCE_NAME,
    BENEFIT_RESOURCE_NAME,
    ORGANIZATION_RESOURCE_NAME,
]

# Per-endpoint ascending sort key. Polar's API default is newest-first (`-created_at` /
# `-started_at`); we override to oldest-first so the destination table is written in row
# creation order. Subscriptions has no `created_at` sort option, so we use `started_at`.
ENDPOINT_SORT_FIELDS: dict[str, str] = {
    CUSTOMER_RESOURCE_NAME: "created_at",
    PRODUCT_RESOURCE_NAME: "created_at",
    ORDER_RESOURCE_NAME: "created_at",
    SUBSCRIPTION_RESOURCE_NAME: "started_at",
    REFUND_RESOURCE_NAME: "created_at",
    CHECKOUT_RESOURCE_NAME: "created_at",
    BENEFIT_RESOURCE_NAME: "created_at",
    ORGANIZATION_RESOURCE_NAME: "created_at",
}
