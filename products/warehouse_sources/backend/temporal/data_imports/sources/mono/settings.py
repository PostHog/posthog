from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://api.withmono.com"
# Relative paths follow the pinned API version. Mono serves bank coverage and Direct Debit only on v3.
ENDPOINTS = {
    "customers": "customers",
    "accounts": "accounts",
    "transactions": "accounts/{account_id}/transactions",
    "institutions": f"{BASE_URL}/v3/institutions",
    "payments": "payments/transactions",
    "mandates": f"{BASE_URL}/v3/payments/mandates",
    "mandate_debits": f"{BASE_URL}/v3/payments/mandates/debits",
}
PRIMARY_KEYS = {
    "customers": ["id"],
    "accounts": ["id"],
    "transactions": ["account_id", "id"],
    "institutions": ["id"],
    "payments": ["id"],
    "mandates": ["id"],
    "mandate_debits": ["mandate", "reference"],
}
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "transactions": [
        {
            "field": "date",
            "type": IncrementalFieldType.DateTime,
            "label": "date",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "payments": [
        {
            "field": "created_at",
            "type": IncrementalFieldType.DateTime,
            "label": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "mandate_debits": [
        {
            "field": "date",
            "type": IncrementalFieldType.DateTime,
            "label": "date",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}
# Date filter query params and their formats for each incremental endpoint.
DATE_FILTERS = {
    "transactions": ("start", "end", "%d-%m-%Y"),
    "payments": ("start", "end", "%d-%m-%Y"),
    "mandate_debits": ("start_date", "end_date", "%Y-%m-%d"),
}
PAGE_SIZE = 100
AUTH_ERROR = "Mono rejected the secret API key. Copy the secret key from your Mono app and reconnect."
PERMISSION_ERROR = "Mono denied access. Check that your Mono app has access to the requested data."
