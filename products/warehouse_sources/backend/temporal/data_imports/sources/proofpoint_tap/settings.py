from datetime import timedelta
from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

BASE_URL = "https://tap-api-v2.proofpoint.com"
API_VERSION = "v2"
API_DOCS_URL = "https://help.proofpoint.com/Threat_Insight_Dashboard/API_Documentation/SIEM_API"
RETENTION = timedelta(days=7)
WINDOW = timedelta(hours=1)
MIN_WINDOW = timedelta(seconds=30)
OVERLAP = timedelta(minutes=1)


# Campaign ID listings accept at most one day per request and allow 50 requests a day.
CAMPAIGN_WINDOW = timedelta(days=1)
CAMPAIGN_PAGE_SIZE = 200
# The People API accepts 14, 30 or 90 days and allows 50 requests a day.
PEOPLE_WINDOW_DAYS = 90


@frozen
class TapEndpoint:
    kind: Literal["siem", "threats", "campaigns", "people"]
    path: str
    selector: str
    primary_key: str
    partition_key: str | None = None
    page_size: int | None = None


ENDPOINTS = {
    "clicks_blocked": TapEndpoint(
        kind="siem", path="siem/clicks/blocked", selector="clicksBlocked", primary_key="id", partition_key="clickTime"
    ),
    "clicks_permitted": TapEndpoint(
        kind="siem",
        path="siem/clicks/permitted",
        selector="clicksPermitted",
        primary_key="id",
        partition_key="clickTime",
    ),
    "messages_blocked": TapEndpoint(
        kind="siem",
        path="siem/messages/blocked",
        selector="messagesBlocked",
        primary_key="GUID",
        partition_key="messageTime",
    ),
    "messages_delivered": TapEndpoint(
        kind="siem",
        path="siem/messages/delivered",
        selector="messagesDelivered",
        primary_key="GUID",
        partition_key="messageTime",
    ),
    "threats": TapEndpoint(
        kind="threats", path="threat/summary/{id}", selector="", primary_key="id", partition_key="identifiedAt"
    ),
    "campaigns": TapEndpoint(
        kind="campaigns",
        path="campaign/{id}",
        selector="campaigns",
        primary_key="id",
        partition_key="startDate",
        page_size=CAMPAIGN_PAGE_SIZE,
    ),
    "very_attacked_people": TapEndpoint(
        kind="people", path="people/vap", selector="users", primary_key="guid", page_size=1000
    ),
    "top_clickers": TapEndpoint(
        kind="people", path="people/top-clickers", selector="users", primary_key="guid", page_size=200
    ),
}

SIEM_ALL_PATH = "siem/all"
CAMPAIGN_IDS_PATH = "campaign/ids"
SIEM_SELECTORS = ("clicksBlocked", "clicksPermitted", "messagesBlocked", "messagesDelivered")

INCREMENTAL_FIELDS = {
    name: [incremental_field("query_end_time")] for name, endpoint in ENDPOINTS.items() if endpoint.kind != "people"
}

AUTH_ERRORS = {
    401: "Proofpoint TAP authentication failed. Check your service principal and secret.",
    403: "Your Proofpoint TAP credentials cannot access this customer's data. Check access in the TAP dashboard.",
}
