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
    "investment_transactions": {
        "description": "An investment transaction (buy, sell, dividend, fee, transfer, etc.) on an investment account belonging to a linked Plaid Item.",
        "docs_url": "https://plaid.com/docs/api/products/investments/#investmentstransactionsget",
        "columns": {
            "investment_transaction_id": "Unique identifier for the investment transaction.",
            "account_id": "ID of the account the transaction posted against.",
            "security_id": "ID of the security the transaction relates to.",
            "date": "Posting date of the transaction, typically the settlement date.",
            "transaction_datetime": "When the order was initiated, for select institutions.",
            "name": "The institution's description of the transaction.",
            "quantity": "Units of the security involved (positive for buys, negative for sells).",
            "amount": "Complete value of the transaction (positive when cash is debited, negative when credited).",
            "price": "Price of the security at which the transaction occurred.",
            "fees": "Combined value of all fees applied to the transaction.",
            "type": "Transaction type (buy, sell, cancel, cash, fee, transfer).",
            "subtype": "Detailed transaction subtype (e.g. dividend, interest, contribution).",
            "iso_currency_code": "ISO-4217 currency code of the transaction.",
        },
    },
    "investment_holdings": {
        "description": "A position in one security held in an investment account belonging to a linked Plaid Item.",
        "docs_url": "https://plaid.com/docs/api/products/investments/#investmentsholdingsget",
        "columns": {
            "account_id": "ID of the account that holds the position.",
            "security_id": "ID of the security held.",
            "quantity": "Total quantity of the security held, as reported by the institution.",
            "cost_basis": "Total cost basis of the holding (the amount spent to acquire the assets currently held).",
            "institution_price": "Last price the institution gave for the security.",
            "institution_price_as_of": "Date at which institution_price was current.",
            "institution_value": "Value of the holding, as reported by the institution.",
            "vested_quantity": "Quantity of vested assets held, for equities.",
            "vested_value": "Value of the vested holdings, as reported by the institution.",
            "iso_currency_code": "ISO-4217 currency code of the holding.",
        },
    },
    "liabilities": {
        "description": "Loan or credit card detail (rates, payments, due dates, origination) for a credit or loan account belonging to a linked Plaid Item.",
        "docs_url": "https://plaid.com/docs/api/products/liabilities/#liabilitiesget",
        "columns": {
            "account_id": "ID of the credit or loan account the liability belongs to.",
            "liability_type": "Kind of liability: credit, mortgage, student, loan, or line_of_credit.",
            "aprs": "Interest rates that apply to a credit card account.",
            "is_overdue": "Whether a payment is currently overdue.",
            "last_payment_amount": "Amount of the last payment.",
            "last_payment_date": "Date of the last payment.",
            "last_statement_balance": "Total amount owed as of the last statement.",
            "minimum_payment_amount": "Minimum payment due for the next billing cycle.",
            "next_payment_due_date": "Due date of the next payment.",
            "origination_date": "Date the loan was originally lent.",
            "origination_principal_amount": "Original principal balance of the loan.",
            "interest_rate": "Interest rate of a mortgage (percentage and type).",
            "interest_rate_percentage": "Interest rate of a student loan, as a percentage.",
            "maturity_date": "Date on which a mortgage is due in full.",
        },
    },
    "institutions": {
        "description": "The financial institution the linked Plaid Item is connected to.",
        "docs_url": "https://plaid.com/docs/api/institutions/#institutionsget_by_id",
        "columns": {
            "institution_id": "Unique identifier for the institution.",
            "name": "Official name of the institution.",
            "products": "Plaid products the institution supports.",
            "country_codes": "Country codes the institution supports.",
            "routing_numbers": "Routing numbers known to be associated with the institution.",
            "oauth": "Whether the institution has an OAuth login flow.",
            "connection_availability": "Whether Plaid supports new connections to the institution.",
        },
    },
}
