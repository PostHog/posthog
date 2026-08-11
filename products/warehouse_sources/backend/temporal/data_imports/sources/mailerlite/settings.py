from dataclasses import dataclass
from typing import Optional


@dataclass
class MailerLiteEndpointConfig:
    name: str
    path: str
    # Stable datetime field used for partitioning. Must be a created-style field that
    # never changes after a row is written (never updated_at). `None` disables partitioning.
    partition_key: Optional[str] = None


# MailerLite's current API (https://connect.mailerlite.com/api) exposes no server-side
# timestamp filter on any list endpoint, so every endpoint is full-refresh only. See
# api_inventory.md for the verification notes. All list responses are flat JSON objects
# wrapped in `{"data": [...], "links": {...}, "meta": {...}}` and paginate by following
# `links.next` (cursor for subscribers, page number for the rest).
MAILERLITE_ENDPOINTS: dict[str, MailerLiteEndpointConfig] = {
    "subscribers": MailerLiteEndpointConfig(
        name="subscribers",
        path="/subscribers",
        partition_key="created_at",
    ),
    "campaigns": MailerLiteEndpointConfig(
        name="campaigns",
        path="/campaigns",
        partition_key="created_at",
    ),
    "groups": MailerLiteEndpointConfig(
        name="groups",
        path="/groups",
        partition_key="created_at",
    ),
    "segments": MailerLiteEndpointConfig(
        name="segments",
        path="/segments",
        partition_key="created_at",
    ),
    "fields": MailerLiteEndpointConfig(
        name="fields",
        path="/fields",
        # Custom field definitions carry no creation timestamp, so they aren't partitioned.
        partition_key=None,
    ),
    "automations": MailerLiteEndpointConfig(
        name="automations",
        path="/automations",
        partition_key="created_at",
    ),
    "forms_popup": MailerLiteEndpointConfig(
        name="forms_popup",
        path="/forms/popup",
        partition_key="created_at",
    ),
    "forms_embedded": MailerLiteEndpointConfig(
        name="forms_embedded",
        path="/forms/embedded",
        partition_key="created_at",
    ),
    "forms_promotion": MailerLiteEndpointConfig(
        name="forms_promotion",
        path="/forms/promotion",
        partition_key="created_at",
    ),
    "webhooks": MailerLiteEndpointConfig(
        name="webhooks",
        path="/webhooks",
        partition_key="created_at",
    ),
}

ENDPOINTS = tuple(MAILERLITE_ENDPOINTS.keys())


# MailerLite names its events `<resource>.<action>`, so the hog template routes on the part
# before the dot and one entry covers every subscriber event.
WEBHOOK_RESOURCE_MAP: dict[str, str] = {"subscribers": "subscriber"}

# Only the events whose delivery carries the whole subscriber object are subscribed, so a
# webhook row is a drop-in replacement for a polled one:
#   - flat events put the subscriber's fields at the payload root next to `event`/`account_id`
#   - the two group events nest the same object under `subscriber`
# Deliberately left out:
#   - `subscriber.deleted` needs `batchable: true`, which changes the delivery envelope, and a
#     deletion can't be expressed as a merge row anyway
#   - `subscriber.automation_triggered` / `subscriber.automation_completed` report automation
#     progress rather than a change to the subscriber's own fields
#   - every `campaign.*` event (see WEBHOOK_SCHEMA_NAMES)
SUBSCRIBER_WEBHOOK_EVENTS: tuple[str, ...] = (
    "subscriber.active",
    "subscriber.added_to_group",
    "subscriber.bounced",
    "subscriber.created",
    "subscriber.removed_from_group",
    "subscriber.spam_reported",
    "subscriber.unsubscribed",
    "subscriber.updated",
)

SCHEMA_TO_WEBHOOK_EVENTS: dict[str, tuple[str, ...]] = {"subscribers": SUBSCRIBER_WEBHOOK_EVENTS}

# `subscribers` is the only webhook-eligible table. `campaigns` is deliberately excluded:
# `campaign.sent` delivers just {id, name, total_recipients, preview_url, date}, a fraction of
# the polled campaign object (status, type, settings, filter, emails, stats), and once a schema
# has webhooks enabled the poll is skipped — so wiring it would drop the columns polling
# collects today. `campaign.open` / `campaign.click` are per-recipient engagement with no event
# id and no event timestamp in the payload, so they can't form a stable primary key or a
# partition/ordering column for a webhook-only table.
WEBHOOK_SCHEMA_NAMES: frozenset[str] = frozenset(SCHEMA_TO_WEBHOOK_EVENTS)

ALL_WEBHOOK_EVENTS: list[str] = sorted({event for events in SCHEMA_TO_WEBHOOK_EVENTS.values() for event in events})


# The new MailerLite API (connect.mailerlite.com) is date-versioned through the `X-Version`
# header and serves the latest version when it's absent. Framework version labels map to that
# header here: `v1` predates version pinning and sends no header (the exact behaviour existing
# sources sync under), `v2` pins MailerLite's documented version date so responses stay on a
# fixed shape instead of silently tracking "latest".
MAILERLITE_V1 = "v1"
MAILERLITE_V2 = "v2"

SUPPORTED_VERSIONS: tuple[str, ...] = (MAILERLITE_V1, MAILERLITE_V2)
DEFAULT_VERSION = MAILERLITE_V2

# `None` means "send no `X-Version` header". `2038-01-19` is the version-pin value MailerLite's
# own docs and official SDK publish for locking the API version.
API_VERSION_HEADERS: dict[str, str | None] = {
    MAILERLITE_V1: None,
    MAILERLITE_V2: "2038-01-19",
}

# A supported version missing from the map would fall through to `None` (no header) and
# silently track "latest" — the drift this framework exists to prevent. Fail loudly instead.
assert set(API_VERSION_HEADERS) == set(SUPPORTED_VERSIONS), (
    "API_VERSION_HEADERS must map every supported MailerLite version"
)
