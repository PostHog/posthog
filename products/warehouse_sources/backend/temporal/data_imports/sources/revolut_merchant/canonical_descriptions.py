from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "orders": {
        "description": "Merchant orders, including payment and refund orders, returned by the legacy order list API.",
        "docs_url": "https://developer.revolut.com/docs/api/merchant/Legacy#retrieve-order-list",
        "columns": {
            "id": "Unique identifier for the order.",
            "created_at": "Time the order was created.",
            "updated_at": "Time the order was last updated.",
            "state": "Current state of the order.",
            "type": "Type of order, such as a payment or refund.",
            "order_amount": "Order amount in minor currency units and its currency.",
            "customer_id": "Identifier of the customer associated with the order.",
        },
    },
    "payments": {
        "description": "Payment attempts for each merchant order, including unsuccessful attempts.",
        "docs_url": "https://developer.revolut.com/docs/api/merchant#retrieve-payment-list",
        "columns": {
            "id": "Identifier for the payment attempt.",
            "order_id": "Identifier of the order this payment belongs to.",
            "created_at": "Time the payment was created.",
            "updated_at": "Time the payment was last updated.",
            "state": "Current state of the payment attempt.",
            "amount": "Payment amount in minor currency units.",
            "currency": "ISO 4217 currency code for the payment amount.",
        },
    },
    "customers": {
        "description": "Customer profiles registered with the merchant account.",
        "docs_url": "https://developer.revolut.com/docs/api/merchant#retrieve-customer-list",
        "columns": {
            "id": "Unique identifier for the customer.",
            "created_at": "Time the customer profile was created.",
            "updated_at": "Time the customer profile was last updated.",
            "email": "Customer email address.",
            "full_name": "Customer full name.",
            "phone": "Customer phone number in E.164 format.",
        },
    },
    "subscriptions": {
        "description": "Customer subscriptions and their current billing status.",
        "docs_url": "https://developer.revolut.com/docs/api/merchant#retrieve-subscription-list",
        "columns": {
            "id": "Unique identifier for the subscription.",
            "created_at": "Time the subscription was created.",
            "updated_at": "Time the subscription was last updated.",
            "state": "Current state of the subscription.",
        },
    },
    "subscription_plans": {
        "description": "Subscription plans configured for the merchant account.",
        "docs_url": "https://developer.revolut.com/docs/api/merchant#retrieve-subscription-plan-list",
        "columns": {
            "id": "Unique identifier for the subscription plan.",
            "created_at": "Time the subscription plan was created.",
            "updated_at": "Time the subscription plan was last updated.",
            "state": "Current state of the subscription plan.",
        },
    },
}
