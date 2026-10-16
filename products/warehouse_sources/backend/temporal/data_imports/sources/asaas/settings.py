from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# All ids are account-wide unique (no fan-out), so every endpoint uses a plain "id" key.
ENDPOINTS = (
    "Customers",
    "Payments",
    "Subscriptions",
    "Transfers",
    "Installments",
    "ReceivedSplits",
    "Invoices",
    "FinancialTransactions",
    "PixTransactions",
)

TABLE_NAMES: dict[str, str] = {
    "Customers": "customers",
    "Payments": "payments",
    "Subscriptions": "subscriptions",
    "Transfers": "transfers",
    "Installments": "installments",
    "ReceivedSplits": "received_splits",
    "Invoices": "invoices",
    "FinancialTransactions": "financial_transactions",
    "PixTransactions": "pix_transactions",
}

# API resource path under `/v3`.
ENDPOINT_PATHS: dict[str, str] = {
    "Customers": "customers",
    "Payments": "payments",
    "Subscriptions": "subscriptions",
    "Transfers": "transfers",
    "Installments": "installments",
    "ReceivedSplits": "payments/splits/received",
    "Invoices": "invoices",
    "FinancialTransactions": "financialTransactions",
    "PixTransactions": "pix/transactions",
}

# Static query params sent on every request for the endpoint.
ENDPOINT_PARAMS: dict[str, dict[str, str]] = {
    "FinancialTransactions": {"order": "asc"},
}

# A stable, never-mutated per-row field to partition on. Received splits only carry a
# nullable `creditDate` and invoices a reschedulable `effectiveDate`, so they aren't partitioned.
PARTITION_KEYS: dict[str, str] = {
    "Customers": "dateCreated",
    "Payments": "dateCreated",
    "Subscriptions": "dateCreated",
    "Transfers": "dateCreated",
    "Installments": "dateCreated",
    "FinancialTransactions": "date",
    "PixTransactions": "dateCreated",
}

# Only endpoints that document a server-side date range filter are incremental.
# Customers, Subscriptions, Installments, and Pix transactions only accept `offset`/`limit` plus
# non-date filters, so a client-side "since" cursor there would still re-fetch every page every run.
# Received splits and invoices filter on dates that move after creation (`creditDate` is set on
# settlement, `effectiveDate` can be rescheduled), so they stay full refresh too.
INCREMENTAL_DATE_PARAMS: dict[str, str] = {
    "Payments": "dateCreated[ge]",
    "Transfers": "dateCreated[ge]",
    "FinancialTransactions": "startDate",
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "Payments": [
        {
            "label": "dateCreated",
            "type": IncrementalFieldType.Date,
            "field": "dateCreated",
            "field_type": IncrementalFieldType.Date,
        },
    ],
    "Transfers": [
        {
            "label": "dateCreated",
            "type": IncrementalFieldType.Date,
            "field": "dateCreated",
            "field_type": IncrementalFieldType.Date,
        },
    ],
    "FinancialTransactions": [
        {
            "label": "date",
            "type": IncrementalFieldType.Date,
            "field": "date",
            "field_type": IncrementalFieldType.Date,
        },
    ],
}
