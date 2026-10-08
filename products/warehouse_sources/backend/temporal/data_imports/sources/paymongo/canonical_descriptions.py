from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "payments": {
        "description": "Payment transactions processed through PayMongo.",
        "docs_url": "https://docs.paymongo.com/reference/list-all-payments",
        "columns": {
            "id": "PayMongo payment identifier.",
            "amount": "Payment amount in the currency's smallest unit.",
            "currency": "Payment currency code.",
            "status": "Payment status.",
            "created_at": "Time the payment was created, in UTC.",
        },
    },
    "refunds": {
        "description": "Refunds associated with payments, including partial refunds.",
        "docs_url": "https://docs.paymongo.com/reference/list-all-refunds",
        "columns": {
            "id": "PayMongo refund identifier.",
            "payment_id": "Identifier of the refunded payment.",
            "amount": "Refund amount in the currency's smallest unit.",
        },
    },
    "links": {
        "description": "Shareable checkout links from the Payment Links API.",
        "docs_url": "https://docs.paymongo.com/reference/get_v1-payment-links",
        "columns": {
            "id": "Payment link identifier.",
            "reference_number": "Reference associated with the payment link.",
            "url": "Checkout URL for the payment link.",
            "status": "Whether the link is active or archived.",
        },
    },
    "payouts": {
        "description": "Payouts with amounts, deductions, destination accounts, and transfer status.",
        "docs_url": "https://docs.paymongo.com/reference/getpayoutlist",
        "columns": {
            "id": "PayMongo payout identifier.",
            "net_amount": "Payout amount after deductions.",
            "status": "Current payout status.",
            "created_at": "Time the payout was created, in UTC.",
        },
    },
    "webhooks": {
        "description": "Registered webhook endpoints and their subscribed events, excluding signing secrets.",
        "docs_url": "https://docs.paymongo.com/reference/list-all-webhooks",
        "columns": {
            "id": "Webhook endpoint identifier.",
            "events": "Event types delivered to this endpoint.",
            "url": "Destination URL for webhook deliveries.",
            "status": "Whether the webhook is enabled or disabled.",
        },
    },
}
