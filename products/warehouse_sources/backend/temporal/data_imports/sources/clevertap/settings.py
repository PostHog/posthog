from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
from products.warehouse_sources.backend.types import IncrementalField

REGIONS = {
    "eu1": "https://api.clevertap.com",
    "us1": "https://us1.api.clevertap.com",
    "in1": "https://in1.api.clevertap.com",
    "sg1": "https://sg1.api.clevertap.com",
    "aps3": "https://aps3.api.clevertap.com",
    "mec1": "https://mec1.api.clevertap.com",
}
PAGE_SIZE = 500
AUTH_ERROR = "CleverTap credentials are invalid. Check the account ID and passcode."
PERMISSION_ERROR = "CleverTap API access is unavailable. Check the account permissions and region."
CURSOR_ERROR = "CleverTap export cursor expired or became invalid. Reset the table sync to start a new export."
EXPORT_ERROR = "CleverTap rejected the export. Check the event name, date range, and API access."
EXCLUDED_EVENTS = {
    "Notification Sent",
    "Notification Bounce",
    "Notification Control Group",
    "Notification Rendered",
    "Notification System Control Group",
}


@frozen
class ClevertapEndpoint:
    path: str
    description: str
    primary_keys: tuple[str, ...] = ()
    partition_key: str | None = None


# Export rows have no documented unique event ID or required, global profile ID.
ENDPOINTS = {
    "events": ClevertapEndpoint(
        path="/1/events.json",
        description="Occurrences of the selected event within the configured date range.",
        partition_key="event_date",
    ),
    "profiles": ClevertapEndpoint(
        path="/1/profiles.json",
        description="Profiles of users who performed the selected event within the configured date range.",
    ),
}
# Date filtering and ordering have no live verification. Profiles have no update timestamp filter.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in ENDPOINTS}

RESPONSE_ACTIONS: list[ResponseAction] = [
    {"status_code": 401, "action": "raise", "message": AUTH_ERROR},
    {"status_code": 403, "action": "raise", "message": PERMISSION_ERROR},
    {"json_field": "code", "json_values": [2], "action": "retry", "message": "CleverTap export is still processing."},
    {
        "json_field": "error",
        "json_values": [
            "Too many requests",
            "Service unavailable. Please retry later",
            "System busy, please retry later",
            "Error processing",
        ],
        "action": "retry",
        "message": "CleverTap export is temporarily unavailable.",
    },
    {"json_field": "code", "json_values": [401], "action": "raise", "message": AUTH_ERROR},
    {"json_field": "code", "json_values": [403], "action": "raise", "message": PERMISSION_ERROR},
    {
        "json_field": "error",
        "json_values": ["Invalid credentials", "Account ID missing", "Account blocked"],
        "action": "raise",
        "message": AUTH_ERROR,
    },
    {
        "json_field": "error",
        "json_values": [
            "Incorrect Usage",
            "Incorrect Usage, stale cursor",
            "Cursor invalidated. Cannot export using this cursor",
            "Invalid cursor",
        ],
        "action": "raise",
        "message": CURSOR_ERROR,
    },
    {"json_field": "code", "json_values": [4004, "CURSOR_INVALIDATED"], "action": "raise", "message": CURSOR_ERROR},
    {"json_field": "status", "json_values": ["CURSOR_INVALIDATED"], "action": "raise", "message": CURSOR_ERROR},
    {"json_field": "status", "json_values": ["fail"], "action": "raise", "message": EXPORT_ERROR},
]
