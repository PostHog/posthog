from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

RECENTLY_PLAYED = "recently_played"
ACCOUNTS = "accounts"

ENDPOINTS = (RECENTLY_PLAYED, ACCOUNTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    RECENTLY_PLAYED: [
        {
            "label": "played_at",
            "type": IncrementalFieldType.DateTime,
            "field": "played_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}

# Each key includes the account, because every table holds rows from all connected accounts.
PRIMARY_KEYS: dict[str, list[str]] = {
    RECENTLY_PLAYED: ["account_id", "played_at"],
    ACCOUNTS: ["account_id"],
}
