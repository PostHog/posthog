from products.warehouse_sources.sources.sdk import IncrementalField, ResponseAction, frozen

REGIONS = {
    "eu1": "https://api.clevertap.com",
    "us1": "https://us1.api.clevertap.com",
    "in1": "https://in1.api.clevertap.com",
    "sg1": "https://sg1.api.clevertap.com",
    "aps3": "https://aps3.api.clevertap.com",
    "mec1": "https://mec1.api.clevertap.com",
}
PAGE_SIZE = 500
CONTENT_BLOCK_PAGE_SIZE = 100
# The campaign list docs advise date ranges of at most 31 days and reject longer spans.
CAMPAIGN_WINDOW_DAYS = 31
AUTH_ERROR = "CleverTap credentials are invalid. Check the account ID and passcode."
PERMISSION_ERROR = "CleverTap API access is unavailable. Check the account permissions and region."
CURSOR_ERROR = "CleverTap export cursor expired or became invalid. Reset the table sync to start a new export."
EXPORT_ERROR = "CleverTap rejected the export. Check the event name, date range, and API access."
REPORT_ERROR = "CleverTap rejected the request. Check the start date and API access."
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


EXPORT_ENDPOINTS = frozenset({"events", "profiles"})
CAMPAIGNS_PATH = "/1/targets/list.json"

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
    "message_reports": ClevertapEndpoint(
        path="/1/message/report.json",
        description=(
            "Messages that started within the configured date range, with channel, status, and delivery metrics. "
            "Some CleverTap accounts allow one message report request each hour, so use an hourly or slower schedule."
        ),
        primary_keys=("message_id",),
    ),
    "campaigns": ClevertapEndpoint(
        path=CAMPAIGNS_PATH,
        description="Campaigns created through the API and scheduled within the configured date range.",
        primary_keys=("id",),
    ),
    "campaign_reports": ClevertapEndpoint(
        path="/1/targets/result.json",
        description="Delivery and click metrics for each completed campaign created through the API.",
        primary_keys=("campaign_id",),
    ),
    "content_blocks": ClevertapEndpoint(
        path="/v1/contentBlock/list",
        description="Reusable content blocks with their content, creator, and update details.",
        primary_keys=("id",),
        partition_key="createdAt",
    ),
}
# Date filtering and ordering have no live verification. Profiles have no update timestamp filter.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in ENDPOINTS}

ACCESS_ACTIONS: list[ResponseAction] = [
    {"status_code": 401, "action": "raise", "message": AUTH_ERROR},
    {"status_code": 403, "action": "raise", "message": PERMISSION_ERROR},
]
RETRY_ACTIONS: list[ResponseAction] = [
    {
        "json_field": "error",
        "json_values": [
            "Too many requests",
            "Service unavailable. Please retry later",
            "System busy, please retry later",
            "Error processing",
        ],
        "action": "retry",
        "message": "CleverTap is temporarily unavailable.",
    },
]
CREDENTIAL_ACTIONS: list[ResponseAction] = [
    {"json_field": "code", "json_values": [401], "action": "raise", "message": AUTH_ERROR},
    {"json_field": "code", "json_values": [403], "action": "raise", "message": PERMISSION_ERROR},
    {
        "json_field": "error",
        "json_values": ["Invalid credentials", "Account ID missing", "Account blocked"],
        "action": "raise",
        "message": AUTH_ERROR,
    },
]
RESPONSE_ACTIONS: list[ResponseAction] = [
    *ACCESS_ACTIONS,
    {"json_field": "code", "json_values": [2], "action": "retry", "message": "CleverTap export is still processing."},
    *RETRY_ACTIONS,
    *CREDENTIAL_ACTIONS,
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
REPORT_RESPONSE_ACTIONS: list[ResponseAction] = [
    *ACCESS_ACTIONS,
    *RETRY_ACTIONS,
    *CREDENTIAL_ACTIONS,
    {"json_field": "status", "json_values": ["fail"], "action": "raise", "message": REPORT_ERROR},
]
# A campaign report is missing until the campaign completes, and a listed campaign can be deleted.
CAMPAIGN_REPORT_RESPONSE_ACTIONS: list[ResponseAction] = [
    {"status_code": 404, "action": "ignore"},
    {"status_code": 409, "action": "ignore"},
    {"json_field": "code", "json_values": [404, 409], "action": "ignore"},
    *REPORT_RESPONSE_ACTIONS,
]
