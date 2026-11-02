from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

CLARI_BASE_URL = "https://api.clari.com/v4"

ENDPOINTS = ("activity", "audit_events", "forecast")

# The export filters to the activity types it is given, so ask for every supported type
# rather than relying on an unset default.
ACTIVITY_TYPES = ("MEETING", "EMAIL_SENT", "EMAIL_RECEIVED", "ATTACHMENT_SENT", "ATTACHMENT_RECEIVED")

# The activity export requires a start date and a first sync has no watermark to derive one from.
ACTIVITY_INITIAL_LOOKBACK_DAYS = 365

# Audit events accept a server-side dateFrom filter and the activity export accepts a
# startDate; the forecast export is a quarter-scoped snapshot with no cursor, so it is
# full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "activity": [
        {
            "label": "date",
            "type": IncrementalFieldType.Integer,
            "field": "date",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
    "audit_events": [
        {
            "label": "eventTimestamp",
            "type": IncrementalFieldType.DateTime,
            "field": "eventTimestamp",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
}
