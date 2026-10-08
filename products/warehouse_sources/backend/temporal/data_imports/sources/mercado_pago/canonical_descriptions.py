from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "payments": {
        "description": "Payments received by the Mercado Pago account within the available search history.",
        "docs_url": "https://www.mercadopago.com.br/developers/en/reference/online-payments/checkout-pro-preferences/search-payments/get",
        "columns": {
            "id": "Unique payment identifier.",
            "date_created": "Time when the payment was created.",
            "date_last_updated": "Time of the most recent payment update.",
            "status": "Payment status.",
            "transaction_amount": "Payment amount in the specified currency.",
            "currency_id": "Currency of the payment.",
            "external_reference": "Reference that links the payment to an external system.",
        },
    },
    "subscriptions": {
        "description": "Recurring payment agreements and their billing schedules.",
        "docs_url": "https://www.mercadopago.com.mx/developers/en/reference/online-payments/subscriptions/search-preapproval/get",
        "columns": {
            "id": "Unique subscription identifier.",
            "preapproval_plan_id": "Identifier of the associated subscription plan.",
            "date_created": "Time when the subscription was created.",
            "last_modified": "Time of the most recent subscription change.",
            "payer_id": "Identifier of the customer who pays for the subscription.",
            "status": "Subscription status.",
            "auto_recurring": "Schedule, amount, and currency for recurring charges.",
        },
    },
    "subscription_plans": {
        "description": "Reusable subscription plans with recurring billing settings.",
        "docs_url": "https://www.mercadopago.com.br/developers/en/reference/online-payments/subscriptions/search-preapproval-plan/get",
        "columns": {
            "id": "Unique subscription plan identifier.",
            "reason": "Description of the subscription plan.",
            "date_created": "Time when the plan was created.",
            "last_modified": "Time of the most recent plan change.",
            "status": "Subscription plan status.",
            "subscribed": "Number of subscriptions associated with the plan.",
            "auto_recurring": "Schedule, amount, and currency for recurring charges.",
        },
    },
}
