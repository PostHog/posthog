"""Canonical, documentation-sourced descriptions for Paystack endpoints and columns.

Sourced from the official Paystack API reference (https://paystack.com/docs/api/). Keyed by the
schema names in `settings.py` `PAYSTACK_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Paystack table. Coverage is partial — any endpoint, column, or table-level description absent
here falls back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Transactions": {
        "description": "Payments collected on your integration, including status, amount, channel and customer.",
        "docs_url": "https://paystack.com/docs/api/transaction/",
        "columns": {
            "id": "Unique integer identifier for the transaction.",
            "reference": "Unique transaction reference you or Paystack assigned.",
            "amount": "Amount of the transaction in the smallest currency unit (e.g. kobo for NGN).",
            "currency": "Currency the transaction was carried out in (e.g. NGN, GHS, ZAR, USD).",
            "status": "Transaction outcome — typically 'success', 'failed' or 'abandoned'.",
            "channel": "Channel the payment was made through (e.g. card, bank, ussd, apple_pay).",
            "gateway_response": "Human-readable response from the payment gateway.",
            "paid_at": "Time the transaction was paid, as an ISO 8601 timestamp.",
            "created_at": "Time the transaction was created, as an ISO 8601 timestamp.",
            "createdAt": "Time the transaction was created, as an ISO 8601 timestamp.",
            "customer": "The customer object associated with the transaction.",
        },
    },
    "Customers": {
        "description": "Customers created on your integration that you can charge and attach subscriptions to.",
        "docs_url": "https://paystack.com/docs/api/customer/",
        "columns": {
            "id": "Unique integer identifier for the customer.",
            "customer_code": "Paystack customer code (format CUS_xxxxxxxx) used across the API.",
            "email": "Customer's email address.",
            "first_name": "Customer's first name.",
            "last_name": "Customer's last name.",
            "phone": "Customer's phone number.",
            "createdAt": "Time the customer was created, as an ISO 8601 timestamp.",
        },
    },
    "Subscriptions": {
        "description": "Recurring billing arrangements linking a customer to a plan.",
        "docs_url": "https://paystack.com/docs/api/subscription/",
        "columns": {
            "id": "Unique integer identifier for the subscription.",
            "subscription_code": "Paystack subscription code (format SUB_xxxxxxxx).",
            "status": "Subscription status (e.g. active, non-renewing, cancelled, complete).",
            "amount": "Amount billed per cycle, in the smallest currency unit.",
            "next_payment_date": "Date the next charge is scheduled, as an ISO 8601 timestamp.",
            "createdAt": "Time the subscription was created, as an ISO 8601 timestamp.",
        },
    },
    "Plans": {
        "description": "Recurring billing templates defining amount, interval and currency.",
        "docs_url": "https://paystack.com/docs/api/plan/",
        "columns": {
            "id": "Unique integer identifier for the plan.",
            "plan_code": "Paystack plan code (format PLN_xxxxxxxx).",
            "name": "Name of the plan.",
            "amount": "Amount charged per interval, in the smallest currency unit.",
            "interval": "Billing interval (e.g. daily, weekly, monthly, annually).",
            "currency": "Currency of the plan.",
            "createdAt": "Time the plan was created, as an ISO 8601 timestamp.",
        },
    },
    "Products": {
        "description": "Products in the Paystack Storefront that customers can purchase.",
        "docs_url": "https://paystack.com/docs/api/product/",
        "columns": {
            "id": "Unique integer identifier for the product.",
            "product_code": "Paystack product code (format PROD_xxxxxxxx).",
            "name": "Name of the product.",
            "price": "Price of the product, in the smallest currency unit.",
            "currency": "Currency of the product price.",
            "createdAt": "Time the product was created, as an ISO 8601 timestamp.",
        },
    },
    "PaymentRequests": {
        "description": "Payment requests (formerly invoices) issued to customers for collection.",
        "docs_url": "https://paystack.com/docs/api/payment-request/",
        "columns": {
            "id": "Unique integer identifier for the payment request.",
            "request_code": "Paystack payment request code (format PRQ_xxxxxxxx).",
            "amount": "Amount requested, in the smallest currency unit.",
            "currency": "Currency of the request.",
            "status": "Status of the payment request (e.g. pending, success).",
            "due_date": "Date payment is due, as an ISO 8601 timestamp.",
            "createdAt": "Time the payment request was created, as an ISO 8601 timestamp.",
        },
    },
    "Settlements": {
        "description": "Payouts of collected funds settled to your bank account or subaccount.",
        "docs_url": "https://paystack.com/docs/api/settlement/",
        "columns": {
            "id": "Unique integer identifier for the settlement.",
            "total_amount": "Total amount settled, in the smallest currency unit.",
            "status": "Settlement status (e.g. success, pending).",
            "settled_by": "Identifier of the entity that processed the settlement.",
            "settlement_date": "Date the settlement was made, as an ISO 8601 timestamp.",
            "createdAt": "Time the settlement was created, as an ISO 8601 timestamp.",
        },
    },
    "Refunds": {
        "description": "Refunds issued against transactions, full or partial.",
        "docs_url": "https://paystack.com/docs/api/refund/",
        "columns": {
            "id": "Unique integer identifier for the refund.",
            "amount": "Amount refunded, in the smallest currency unit.",
            "currency": "Currency of the refund.",
            "status": "Refund status (e.g. pending, processed, failed).",
            "transaction": "Identifier of the transaction being refunded.",
            "createdAt": "Time the refund was created, as an ISO 8601 timestamp.",
        },
    },
    "Transfers": {
        "description": "Money sent from your integration to transfer recipients.",
        "docs_url": "https://paystack.com/docs/api/transfer/",
        "columns": {
            "id": "Unique integer identifier for the transfer.",
            "transfer_code": "Paystack transfer code (format TRF_xxxxxxxx).",
            "amount": "Amount transferred, in the smallest currency unit.",
            "currency": "Currency of the transfer.",
            "status": "Transfer status (e.g. pending, success, failed).",
            "reference": "Unique reference for the transfer.",
            "createdAt": "Time the transfer was created, as an ISO 8601 timestamp.",
        },
    },
    "TransferRecipients": {
        "description": "Recipients (bank accounts or cards) you can send transfers to.",
        "docs_url": "https://paystack.com/docs/api/transfer-recipient/",
        "columns": {
            "id": "Unique integer identifier for the transfer recipient.",
            "recipient_code": "Paystack recipient code (format RCP_xxxxxxxx).",
            "type": "Recipient type (e.g. nuban, mobile_money, basa).",
            "name": "Name of the recipient.",
            "currency": "Currency the recipient is settled in.",
            "createdAt": "Time the recipient was created, as an ISO 8601 timestamp.",
        },
    },
    "Disputes": {
        "description": "Chargebacks and disputes raised against your transactions.",
        "docs_url": "https://paystack.com/docs/api/dispute/",
        "columns": {
            "id": "Unique integer identifier for the dispute.",
            "status": "Dispute status (e.g. awaiting-merchant-feedback, resolved).",
            "currency": "Currency of the disputed transaction.",
            "transaction": "The transaction being disputed.",
            "resolution": "Resolution outcome of the dispute, when settled.",
            "createdAt": "Time the dispute was created, as an ISO 8601 timestamp.",
        },
    },
    "Subaccounts": {
        "description": "Subaccounts used to split settlement of payments to other bank accounts.",
        "docs_url": "https://paystack.com/docs/api/subaccount/",
        "columns": {
            "id": "Unique integer identifier for the subaccount.",
            "subaccount_code": "Paystack subaccount code (format ACCT_xxxxxxxx).",
            "business_name": "Business name registered on the subaccount.",
            "percentage_charge": "Default percentage of transactions allocated to the subaccount.",
            "settlement_bank": "Bank the subaccount settles to.",
            "createdAt": "Time the subaccount was created, as an ISO 8601 timestamp.",
        },
    },
    "PaymentPages": {
        "description": "Hosted payment pages customers can use to pay you.",
        "docs_url": "https://paystack.com/docs/api/page/",
        "columns": {
            "id": "Unique integer identifier for the payment page.",
            "slug": "URL slug of the payment page.",
            "name": "Name of the payment page.",
            "amount": "Fixed amount for the page, in the smallest currency unit (may be null).",
            "currency": "Currency of the page.",
            "active": "Whether the payment page is currently active.",
            "createdAt": "Time the payment page was created, as an ISO 8601 timestamp.",
        },
    },
}
