from datetime import timedelta

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

BASE_URL = "https://tap-api-v2.proofpoint.com"
API_VERSION = "v2"
API_DOCS_URL = "https://help.proofpoint.com/Threat_Insight_Dashboard/API_Documentation/SIEM_API"
RETENTION = timedelta(days=7)
WINDOW = timedelta(hours=1)
MIN_WINDOW = timedelta(seconds=30)
OVERLAP = timedelta(minutes=1)


@frozen
class TapEndpoint:
    path: str
    selector: str
    primary_key: str
    event_time: str


ENDPOINTS = {
    "clicks_blocked": TapEndpoint(
        path="clicks/blocked", selector="clicksBlocked", primary_key="id", event_time="clickTime"
    ),
    "clicks_permitted": TapEndpoint(
        path="clicks/permitted", selector="clicksPermitted", primary_key="id", event_time="clickTime"
    ),
    "messages_blocked": TapEndpoint(
        path="messages/blocked", selector="messagesBlocked", primary_key="GUID", event_time="messageTime"
    ),
    "messages_delivered": TapEndpoint(
        path="messages/delivered", selector="messagesDelivered", primary_key="GUID", event_time="messageTime"
    ),
}

INCREMENTAL_FIELDS = {name: [incremental_field("query_end_time")] for name in ENDPOINTS}

AUTH_ERRORS = {
    401: "Proofpoint TAP authentication failed. Check your service principal and secret.",
    403: "Your Proofpoint TAP credentials cannot access this customer's data. Check access in the TAP dashboard.",
}
