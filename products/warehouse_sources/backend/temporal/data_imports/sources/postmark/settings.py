from dataclasses import dataclass
from typing import Optional

# Postmark caps `count + offset` at 10,000 on its paginated list endpoints, so a full
# refresh can only reach the most recent 10,000 rows for those endpoints. See the module
# docstring in `postmark.py` for the data-retention/window caveats.
POSTMARK_MAX_WINDOW = 10_000
# Postmark allows at most 500 rows per page on its paginated list endpoints.
POSTMARK_MAX_PAGE_SIZE = 500


@dataclass
class PostmarkEndpointConfig:
    name: str
    path: str
    # Key in the JSON response body that holds the list of rows (Postmark wraps every
    # list response, e.g. `{"TotalCount": N, "Messages": [...]}`).
    data_key: str
    primary_key: str = "ID"
    # Stable datetime field used for partitioning. Never an `updated_at`-style field.
    partition_key: Optional[str] = None
    # Offset/count-paginated endpoints set a page size (max 500). Flat endpoints return
    # the whole list in a single response and leave this `None`.
    page_size: Optional[int] = None


POSTMARK_ENDPOINTS: dict[str, PostmarkEndpointConfig] = {
    "messages_outbound": PostmarkEndpointConfig(
        name="messages_outbound",
        path="/messages/outbound",
        data_key="Messages",
        primary_key="MessageID",
        partition_key="ReceivedAt",
        page_size=POSTMARK_MAX_PAGE_SIZE,
    ),
    "messages_inbound": PostmarkEndpointConfig(
        name="messages_inbound",
        path="/messages/inbound",
        data_key="InboundMessages",
        primary_key="MessageID",
        partition_key="ReceivedAt",
        page_size=POSTMARK_MAX_PAGE_SIZE,
    ),
    "bounces": PostmarkEndpointConfig(
        name="bounces",
        path="/bounces",
        data_key="Bounces",
        primary_key="ID",
        partition_key="BouncedAt",
        page_size=POSTMARK_MAX_PAGE_SIZE,
    ),
    "templates": PostmarkEndpointConfig(
        name="templates",
        path="/templates",
        data_key="Templates",
        primary_key="TemplateId",
        page_size=POSTMARK_MAX_PAGE_SIZE,
    ),
    "message_streams": PostmarkEndpointConfig(
        name="message_streams",
        path="/message-streams",
        data_key="MessageStreams",
        primary_key="ID",
    ),
}


ENDPOINTS = tuple(POSTMARK_ENDPOINTS.keys())
