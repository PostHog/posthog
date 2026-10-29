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
    "payout_transactions": {
        "description": "Payments, refunds, disputes, and adjustments settled in each payout.",
        "docs_url": "https://docs.paymongo.com/reference/getpayouttransactions",
        "columns": {
            "id": "Transaction identifier, such as a payment, refund, or dispute ID.",
            "_payouts_id": "Identifier of the payout this transaction belongs to.",
            "type": "Transaction type, such as payment, refund, dispute, or adjustment.",
            "amount": "Transaction amount in the currency's smallest unit.",
            "fee": "Transaction fee, for payments.",
            "net_amount": "Transaction amount after fees.",
            "balance_transaction_id": "Identifier of the associated balance transaction.",
            "created_at": "Time the transaction was created, in UTC.",
        },
    },
    "subscriptions": {
        "description": "Recurring billing subscriptions that link customers to plans.",
        "docs_url": "https://docs.paymongo.com/reference/subscription-resource",
        "columns": {
            "id": "PayMongo subscription identifier.",
            "customer_id": "Identifier of the subscribed customer.",
            "plan": "Plan the customer subscribes to, with amount and billing interval.",
            "status": "Current subscription status.",
            "latest_invoice": "Most recent invoice generated for the subscription.",
            "next_billing_schedule": "Date of the next billing cycle.",
        },
    },
    "invoices": {
        "description": "Sales invoices sent to customers, with amounts due, payment status, and due dates.",
        "docs_url": "https://docs.paymongo.com/reference/list_invoices-2",
        "columns": {
            "id": "PayMongo invoice identifier.",
            "number": "Invoice number shown to the customer.",
            "status": "Invoice status, such as draft, open, paid, overdue, or void.",
            "amount_due": "Amount still due, in the currency's smallest unit.",
            "amount_paid": "Amount already paid, in the currency's smallest unit.",
            "due_at": "Time the invoice payment is due.",
            "created_at": "Time the invoice was created.",
        },
    },
}
