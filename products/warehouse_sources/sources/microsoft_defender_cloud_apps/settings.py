from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = ("alerts", "files", "entities")
PAGE_SIZE = 100
PRIMARY_KEYS: dict[str, list[str] | None] = {"alerts": ["_id"], "files": None, "entities": None}
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "alerts": [
        {
            "field": "timestamp",
            "label": "Alert time (milliseconds)",
            "type": IncrementalFieldType.Integer,
            "field_type": IncrementalFieldType.Integer,
        }
    ]
}

AUTH_ERROR = "Your API token is invalid or expired. Create a new token in Microsoft Defender and reconnect."
PERMISSION_ERROR = (
    "Your API token cannot read this data. Check the token owner's permissions and your Defender license."
)
