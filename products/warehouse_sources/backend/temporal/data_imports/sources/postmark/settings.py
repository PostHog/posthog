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


# --- Webhook ingestion -------------------------------------------------------------------
#
# Postmark's Bounce and SpamComplaint webhooks serialize the same bounce record the Bounce API
# lists, field for field, so both feed the `bounces` table. The other triggers (Delivery, Open,
# Click, SubscriptionChange) describe message events we have no table for, and inbound webhooks
# are configured on the server rather than through the Webhooks API — neither is wired up.

# Schemas that can be fed by pushed rows as well as the backfill.
WEBHOOK_SCHEMA_NAMES = frozenset({"bounces"})

# Schema name -> the `schema_mapping` key incoming deliveries are routed by.
WEBHOOK_RESOURCE_MAP = {"bounces": "Bounce"}

# Triggers we subscribe to. `IncludeContent` stays off so pushed rows carry the same fields the
# Bounce API list response does (the raw dump is only available per-bounce).
WEBHOOK_TRIGGERS: dict[str, dict[str, bool]] = {
    "Bounce": {"Enabled": True, "IncludeContent": False},
    "SpamComplaint": {"Enabled": True, "IncludeContent": False},
}

# Webhooks are per message stream. The `bounces` backfill doesn't pass `messagestream`, which
# Postmark defaults to `outbound`, so subscribing the same stream keeps push and pull covering
# the same rows.
WEBHOOK_MESSAGE_STREAM = "outbound"

# Postmark doesn't sign deliveries, but the Webhooks API lets us pin static headers onto a
# webhook. `create_webhook` sets a generated secret here and the template requires it back.
WEBHOOK_SECRET_HEADER = "x-posthog-webhook-secret"

# Fields a webhook delivery carries that the Bounce API list response does not. `Metadata` holds
# arbitrary user-defined keys, so keeping it would evolve the table schema on every new key.
WEBHOOK_ONLY_FIELDS = ("Metadata", "Content")
