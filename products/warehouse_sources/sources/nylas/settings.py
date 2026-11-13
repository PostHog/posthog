from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

NYLAS_API_VERSION = "v3"

# The region is a fixed choice, never a typed-in host, so the API key can only reach Nylas.
NYLAS_REGION_BASE_URLS: dict[str, str] = {
    "us": "https://api.us.nylas.com",
    "eu": "https://api.eu.nylas.com",
}
DEFAULT_REGION = "us"

GrantScope = Literal["all", "agent_accounts", "connected_accounts"]
DEFAULT_GRANT_SCOPE: GrantScope = "all"
# An Agent Account is a grant whose provider is `nylas`.
AGENT_ACCOUNT_PROVIDER = "nylas"

GRANTS_PAGE_SIZE = 200

# The list-events endpoint only returns the next month unless it gets a time range.
DEFAULT_EVENT_HISTORY_DAYS = 365
EVENT_FUTURE_DAYS = 365
# iCloud rejects a time range longer than six months.
ICLOUD_PROVIDER = "icloud"
ICLOUD_MAX_EVENT_WINDOW_DAYS = 180
# Providers that support the `updated_after` filter on events.
EVENT_UPDATED_FILTER_PROVIDERS = frozenset({"google", "microsoft", "ews"})
# Google rejects an `updated_after` more than 28 days back, and Nylas returns that as a 404.
# An older watermark reads the whole time range instead.
EVENT_UPDATED_FILTER_MAX_AGE_DAYS = 21
GOOGLE_UPDATED_FILTER_TOO_OLD = "updatedMinTooLongAgo"
# Providers that reject `show_cancelled`.
EVENT_NO_CANCELLED_PROVIDERS = frozenset({"icloud", "ews"})


@dataclass(frozen=True)
class NylasEndpointConfig:
    name: str
    # `{grant_id}` marks an endpoint that is read once per grant.
    path: str
    primary_keys: list[str]
    page_size: int
    per_grant: bool = True
    # Stable Unix-seconds field used for partitioning.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Query param that takes the incremental watermark as Unix seconds.
    incremental_param: Optional[str] = None
    description: Optional[str] = None
    # Static query params sent on every request.
    extra_params: dict[str, str] = field(default_factory=dict)
    # `data.object.object` of the notifications that feed this table, and the triggers to
    # subscribe to. Nylas adds the `.truncated` and `.transformed` variants of the message
    # triggers on its own, with no separate subscription.
    webhook_object_type: Optional[str] = None
    webhook_triggers: tuple[str, ...] = ()


def _unix_seconds_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.Integer,
    }


NYLAS_ENDPOINTS: dict[str, NylasEndpointConfig] = {
    "grants": NylasEndpointConfig(
        name="grants",
        path="/v3/grants",
        primary_keys=["id"],
        page_size=GRANTS_PAGE_SIZE,
        per_grant=False,
        partition_key="created_at",
        description="Connected accounts and Agent Accounts in your Nylas application",
    ),
    "messages": NylasEndpointConfig(
        name="messages",
        path="/v3/grants/{grant_id}/messages",
        # Message IDs come from the email provider, so they are only unique within a grant.
        primary_keys=["grant_id", "id"],
        page_size=100,
        partition_key="date",
        incremental_fields=[_unix_seconds_field("date")],
        incremental_param="received_after",
        description="Email messages from each grant, with one row per (grant, message)",
        webhook_object_type="message",
        webhook_triggers=("message.created", "message.updated"),
    ),
    "threads": NylasEndpointConfig(
        name="threads",
        path="/v3/grants/{grant_id}/threads",
        primary_keys=["grant_id", "id"],
        page_size=50,
        partition_key="earliest_message_date",
        # No incremental sync: `latest_message_after` filters on the last received message, so
        # it leaves out a thread whose messages were all sent.
        description="Email threads from each grant, with one row per (grant, thread)",
    ),
    "folders": NylasEndpointConfig(
        name="folders",
        path="/v3/grants/{grant_id}/folders",
        primary_keys=["grant_id", "id"],
        page_size=200,
        description="Folders and labels from each grant, with one row per (grant, folder)",
    ),
    "calendars": NylasEndpointConfig(
        name="calendars",
        path="/v3/grants/{grant_id}/calendars",
        primary_keys=["grant_id", "id"],
        page_size=200,
        description="Calendars from each grant, with one row per (grant, calendar)",
    ),
    "events": NylasEndpointConfig(
        name="events",
        path="/v3/grants/{grant_id}/events",
        # The same event can sit in two calendars of one grant.
        primary_keys=["grant_id", "calendar_id", "id"],
        page_size=200,
        incremental_fields=[_unix_seconds_field("updated_at")],
        incremental_param="updated_after",
        description=(
            "Calendar events from every calendar of each grant, with one row per (grant, calendar, event). "
            "Recurring events are one row for the series, plus one row per changed occurrence"
        ),
        # Expanded occurrences have no stable end and repeat the series row.
        extra_params={"expand_recurring": "false"},
        webhook_object_type="event",
        webhook_triggers=("event.created", "event.updated", "event.deleted"),
    ),
    "contacts": NylasEndpointConfig(
        name="contacts",
        path="/v3/grants/{grant_id}/contacts",
        primary_keys=["grant_id", "id"],
        page_size=200,
        description="Address book contacts from each grant, with one row per (grant, contact)",
        webhook_object_type="contact",
        webhook_triggers=("contact.updated",),
    ),
}

ENDPOINTS = tuple(NYLAS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in NYLAS_ENDPOINTS.items() if config.incremental_fields
}

# Schema name -> the `data.object.object` value of the notifications that feed it.
WEBHOOK_RESOURCE_MAP: dict[str, str] = {
    name: config.webhook_object_type for name, config in NYLAS_ENDPOINTS.items() if config.webhook_object_type
}

WEBHOOK_TRIGGERS: tuple[str, ...] = tuple(
    trigger for config in NYLAS_ENDPOINTS.values() for trigger in config.webhook_triggers
)
