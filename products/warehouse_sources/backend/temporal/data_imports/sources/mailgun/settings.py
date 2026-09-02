from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import PartitionFormat
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

PaginationStyle = Literal["paging", "skip"]


@dataclass
class MailgunEndpointConfig:
    name: str
    # Path relative to the regional API host. Contains a `{domain}` placeholder for
    # domain-scoped endpoints, which fan out over every sending domain on the account.
    path: str
    domain_scoped: bool = False
    # "paging" endpoints return opaque next/previous URLs in a `paging` object and
    # terminate with an empty `items` page; "skip" endpoints use limit/skip offsets.
    pagination: PaginationStyle = "paging"
    page_size: int = 100
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field used for datetime partitioning. Never an updated_at-style
    # field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    partition_format: Optional[PartitionFormat] = None


# Only the Events API exposes a server-side timestamp filter (`begin`/`end` epoch seconds
# with `ascending=yes`), so it's the only endpoint advertised as incremental. Domains,
# suppressions, mailing lists, tags, and templates have no updated-at filter — full
# refresh only. Domain-scoped rows get a `domain` column injected so primary keys stay
# unique across domains.
MAILGUN_ENDPOINTS: dict[str, MailgunEndpointConfig] = {
    "domains": MailgunEndpointConfig(
        name="domains",
        path="/v4/domains",
        pagination="skip",
        page_size=1000,
        primary_keys=["id"],
    ),
    "events": MailgunEndpointConfig(
        name="events",
        path="/v3/{domain}/events",
        domain_scoped=True,
        # Events API caps pages at 300 items.
        page_size=300,
        primary_keys=["domain", "id"],
        partition_key="timestamp",
        partition_format="day",
        incremental_fields=[
            {
                "label": "timestamp",
                "type": IncrementalFieldType.DateTime,
                "field": "timestamp",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "bounces": MailgunEndpointConfig(
        name="bounces",
        path="/v3/{domain}/bounces",
        domain_scoped=True,
        page_size=1000,
        primary_keys=["domain", "address"],
        partition_key="created_at",
        partition_format="month",
    ),
    "complaints": MailgunEndpointConfig(
        name="complaints",
        path="/v3/{domain}/complaints",
        domain_scoped=True,
        page_size=1000,
        primary_keys=["domain", "address"],
        partition_key="created_at",
        partition_format="month",
    ),
    "unsubscribes": MailgunEndpointConfig(
        name="unsubscribes",
        path="/v3/{domain}/unsubscribes",
        domain_scoped=True,
        page_size=1000,
        primary_keys=["domain", "address"],
        partition_key="created_at",
        partition_format="month",
    ),
    "mailing_lists": MailgunEndpointConfig(
        name="mailing_lists",
        path="/v3/lists/pages",
        page_size=100,
        primary_keys=["address"],
    ),
    "tags": MailgunEndpointConfig(
        name="tags",
        path="/v3/{domain}/tags",
        domain_scoped=True,
        page_size=1000,
        primary_keys=["domain", "tag"],
    ),
    "templates": MailgunEndpointConfig(
        name="templates",
        path="/v3/{domain}/templates",
        domain_scoped=True,
        # Left at 100 until someone confirms the cap against a live account: the docs only state
        # 1000 for tags. A rejected `limit` returns 400, which the fan-out reads as an unqueryable
        # domain and skips, so guessing too high loses the endpoint on every domain with a warning.
        page_size=100,
        # Template names are unique per domain; list items aren't guaranteed an `id`.
        primary_keys=["domain", "name"],
    ),
}

ENDPOINTS = tuple(MAILGUN_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in MAILGUN_ENDPOINTS.items() if config.incremental_fields
}

# Webhook-only table fed by Mailgun's pushed event stream. It deliberately does not feed the
# polled `events` table: that table's primary key is ["domain", "id"] and the sending domain is
# injected by our per-domain fan-out, not returned by Mailgun, so webhook rows could never merge
# against polled rows. The polled table also carries `rejected`, `stored` and list-upload events
# that Mailgun offers no webhook for, and a schema in webhook mode skips its poll entirely.
WEBHOOK_EVENTS_ENDPOINT = "webhook_events"

# Webhook type ids accepted by POST /v3/domains/{domain}/webhooks. Registered on every sending
# domain so the pushed stream covers the whole account. Note `unsubscribe` — the webhook id and
# the `event` value in its payload (`unsubscribed`) differ.
WEBHOOK_TYPES: tuple[str, ...] = (
    "accepted",
    "clicked",
    "complained",
    "delivered",
    "opened",
    "permanent_fail",
    "temporary_fail",
    "unsubscribe",
)

# Every webhook type lands in the one webhook-only table, so the hog template collapses the
# payload's `event` value to this resource key before looking up the schema id.
WEBHOOK_RESOURCE_KEY = "email_event"

SCHEMA_TO_WEBHOOK_RESOURCE: dict[str, str] = {WEBHOOK_EVENTS_ENDPOINT: WEBHOOK_RESOURCE_KEY}

# `event-data.event` values the webhook types above deliver. `permanent_fail` and
# `temporary_fail` both arrive as `failed`, told apart by the payload's `severity`.
WEBHOOK_EVENT_NAMES: tuple[str, ...] = (
    "accepted",
    "clicked",
    "complained",
    "delivered",
    "failed",
    "opened",
    "unsubscribed",
)
