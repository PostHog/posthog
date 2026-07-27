"""Canonical, documentation-sourced descriptions for Plaid endpoints and columns.

Sourced from the official Plaid API reference (https://plaid.com/docs/api/). Keyed by the endpoint
names in `settings.py` `PLAID_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced Plaid
table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "accounts": {
        "description": "A financial account (checking, savings, credit card, loan, etc.) belonging to a linked Plaid Item.",
        "docs_url": "https://plaid.com/docs/api/accounts/#accountsget",
        "columns": {
            "account_id": "Unique identifier for the account.",
            "name": "The account's name, as provided by the institution.",
            "official_name": "The official name of the account, as provided by the institution.",
            "mask": "The last 2-4 digits of the account number.",
            "type": "Account type (e.g. depository, credit, loan, investment).",
            "subtype": "Account subtype (e.g. checking, savings, credit card).",
            "balances": "Balance information for the account (available, current, limit, currency).",
            "verification_status": "Status of account/routing number verification, if applicable.",
        },
    },
    "transactions": {
        "description": "A transaction (purchase, transfer, etc.) on an account belonging to a linked Plaid Item.",
        "docs_url": "https://plaid.com/docs/api/products/transactions/#transactionsget",
        "columns": {
            "transaction_id": "Unique identifier for the transaction.",
            "account_id": "ID of the account the transaction belongs to.",
            "amount": "Settled amount of the transaction (positive = money leaving the account).",
            "iso_currency_code": "ISO-4217 currency code of the transaction amount.",
            "date": "Date the transaction posted or was authorized.",
            "datetime": "Date and time the transaction posted, when available.",
            "authorized_date": "Date the transaction was authorized.",
            "name": "Merchant name or transaction description.",
            "merchant_name": "Cleaned merchant name for the transaction.",
            "pending": "Whether the transaction is pending or has posted.",
            "pending_transaction_id": "ID of the pending transaction this posted transaction replaced, if any.",
            "payment_channel": "How the transaction took place (online, in store, or other).",
            "category": "Hierarchical category labels for the transaction (legacy taxonomy).",
            "personal_finance_category": "Detailed and primary personal finance category for the transaction.",
        },
    },
}
