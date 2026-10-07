from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

EVENTS = "events"
ACCOUNTS = "accounts"

ENDPOINTS = (EVENTS, ACCOUNTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    EVENTS: [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}

# Each key includes the account, because every table holds rows from all connected accounts.
PRIMARY_KEYS: dict[str, list[str]] = {
    EVENTS: ["account_id", "id"],
    ACCOUNTS: ["account_id"],
}
