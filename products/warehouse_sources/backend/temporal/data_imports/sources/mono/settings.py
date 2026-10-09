from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://api.withmono.com"
ENDPOINTS = {
    "customers": "customers",
    "accounts": "accounts",
    "transactions": "accounts/{account_id}/transactions",
}
PRIMARY_KEYS = {
    "customers": ["id"],
    "accounts": ["id"],
    "transactions": ["account_id", "id"],
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
}
AUTH_ERROR = "Mono rejected the secret API key. Copy the secret key from your Mono app and reconnect."
PERMISSION_ERROR = "Mono denied access. Check that your Mono app has access to the requested data."
