CUSTOMER_RESOURCE_NAME = "customers"
DISCOUNT_RESOURCE_NAME = "discounts"
PRICE_RESOURCE_NAME = "prices"
PRODUCT_RESOURCE_NAME = "products"
SUBSCRIPTION_RESOURCE_NAME = "subscriptions"
TRANSACTION_RESOURCE_NAME = "transactions"
ADJUSTMENT_RESOURCE_NAME = "adjustments"

# Maps PostHog schema name -> Paddle event_type prefix (the entity type carried in webhook `data`).
# Values become the webhook HogFunction's schema_mapping keys; the Hog template routes on the
# prefix before the first "." in event_type (e.g. "transaction.completed" -> "transaction").
RESOURCE_TO_PADDLE_ENTITY: dict[str, str] = {
    CUSTOMER_RESOURCE_NAME: "customer",
    DISCOUNT_RESOURCE_NAME: "discount",
    PRICE_RESOURCE_NAME: "price",
    PRODUCT_RESOURCE_NAME: "product",
    SUBSCRIPTION_RESOURCE_NAME: "subscription",
    TRANSACTION_RESOURCE_NAME: "transaction",
    ADJUSTMENT_RESOURCE_NAME: "adjustment",
}

# Description stamped on the auto-created Paddle notification destination.
PADDLE_AUTO_WEBHOOK_DESCRIPTION = "PostHog data warehouse webhook"
