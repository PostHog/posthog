from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

CLARI_BASE_URL = "https://api.clari.com/v4"

ENDPOINTS = ("audit_events", "forecast")

# Audit events accept a server-side dateFrom filter; the forecast export is a
# quarter-scoped snapshot with no cursor, so it is full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "audit_events": [
        {
            "label": "eventTimestamp",
            "type": IncrementalFieldType.DateTime,
            "field": "eventTimestamp",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
}
