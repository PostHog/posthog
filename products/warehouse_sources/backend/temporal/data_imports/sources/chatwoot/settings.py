from dataclasses import dataclass, field
from typing import Literal, Optional

DEFAULT_HOST = "https://app.chatwoot.com"

# Server-side fixed page sizes — Chatwoot exposes no per-page override param.
CONTACTS_PAGE_SIZE = 15
# `after`-cursor pages on the messages endpoint return up to 100 rows (MessageFinder#messages_after).
MESSAGES_PAGE_SIZE = 100

# The REST API returns `message_type` as an integer enum; webhook payloads carry the string form.
MESSAGE_TYPE_TO_INT = {"incoming": 0, "outgoing": 1, "activity": 2, "template": 3}


@dataclass
class ChatwootEndpointConfig:
    name: str
    # Path under /api/v1/accounts/{account_id}.
    path: str
    # "paged": page-number list. "single": one unpaginated response. "messages": the
    # per-conversation fan-out with an id-based `after` cursor.
    kind: Literal["paged", "single", "messages"]
    # Where the row list lives in the response body; () means the body is a bare JSON array.
    data_path: tuple[str, ...] = ()
    # Query params sent on every request.
    params: dict[str, str] = field(default_factory=dict)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time field for datetime partitioning (unix epoch ints in Chatwoot list
    # responses). Never an updated_at-style field.
    partition_key: Optional[str] = None
    supports_webhooks: bool = False
    description: Optional[str] = None


# No endpoint here declares incremental sync: Chatwoot's list endpoints expose no server-side
# timestamp filter (no updated_since/created_since), so every pull is a full walk. Webhooks are
# the delta path for conversations and messages.
CHATWOOT_ENDPOINTS: dict[str, ChatwootEndpointConfig] = {
    "conversations": ChatwootEndpointConfig(
        name="conversations",
        path="/conversations",
        kind="paged",
        data_path=("data", "payload"),
        # `status` defaults to "open" server-side; "all" disables the filter. created_at_asc keeps
        # page-number pagination stable while new conversations arrive mid-sync (new rows append
        # to the tail instead of reshuffling already-fetched pages).
        params={"status": "all", "sort_by": "created_at_asc"},
        partition_key="created_at",
        supports_webhooks=True,
        description="One row per conversation. The id column is Chatwoot's per-account display id.",
    ),
    "messages": ChatwootEndpointConfig(
        name="messages",
        path="/conversations/{conversation_id}/messages",
        kind="messages",
        data_path=("payload",),
        partition_key="created_at",
        supports_webhooks=True,
        description=(
            "Conversation messages, fetched per conversation — a full sync issues at least one "
            "request per conversation, so large accounts can take a while. Webhook sync avoids "
            "the re-walk after the initial backfill."
        ),
    ),
    "contacts": ChatwootEndpointConfig(
        name="contacts",
        path="/contacts",
        kind="paged",
        data_path=("payload",),
        # Ascending creation order keeps page-number pagination stable mid-sync.
        params={"sort": "created_at"},
        partition_key="created_at",
        description=(
            "Contacts with an email, phone number, or identifier. Chatwoot's contact list "
            "excludes anonymous web-widget visitors."
        ),
    ),
    "inboxes": ChatwootEndpointConfig(
        name="inboxes",
        path="/inboxes",
        kind="single",
        data_path=("payload",),
    ),
    "agents": ChatwootEndpointConfig(
        name="agents",
        path="/agents",
        kind="single",
    ),
    "teams": ChatwootEndpointConfig(
        name="teams",
        path="/teams",
        kind="single",
    ),
    "labels": ChatwootEndpointConfig(
        name="labels",
        path="/labels",
        kind="single",
        data_path=("payload",),
    ),
    "custom_attribute_definitions": ChatwootEndpointConfig(
        name="custom_attribute_definitions",
        path="/custom_attribute_definitions",
        kind="single",
        description="Custom attribute definitions for conversations, contacts, and companies.",
    ),
}

ENDPOINTS = tuple(CHATWOOT_ENDPOINTS.keys())

# Maps our schema names to the object type a webhook event carries. The webhook template derives
# the object type from the event name prefix (message_created -> "message").
RESOURCE_TO_WEBHOOK_OBJECT_TYPE: dict[str, str] = {
    "conversations": "conversation",
    "messages": "message",
}

RESOURCE_TO_WEBHOOK_EVENTS: dict[str, list[str]] = {
    "conversations": ["conversation_created", "conversation_updated", "conversation_status_changed"],
    "messages": ["message_created", "message_updated"],
}


def all_webhook_events() -> list[str]:
    """Every event we can map to a schema. Re-derived on each reconcile so webhooks created
    before the map grew are auto-healed."""
    return [event for events in RESOURCE_TO_WEBHOOK_EVENTS.values() for event in events]
