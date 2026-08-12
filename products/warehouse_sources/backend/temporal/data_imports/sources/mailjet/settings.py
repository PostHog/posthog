from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class MailjetEndpointConfig:
    name: str
    path: str  # resource segment under /v3/REST/, e.g. "contact"
    primary_key: str = "ID"
    # Stable timestamp field for datetime partitioning. None disables partitioning.
    partition_key: Optional[str] = None
    # Mailjet `Sort` value. Default to the monotonic ID so offset pagination is
    # deterministic even if rows are inserted mid-sync.
    sort: Optional[str] = "ID"
    page_size: int = 1000  # Mailjet `Limit` maxes out at 1000
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # When set, the endpoint supports server-side time windows via the `FromTS`
    # filter (Unix timestamp); enables real incremental sync.
    from_ts_field: Optional[str] = None


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


# NOTE: per-endpoint field casing (PK / partition / sort) and `FromTS` support must be
# confirmed against the live API with real credentials. Fields that cannot be confirmed
# fall back to partition_key=None and sort="ID".
MAILJET_ENDPOINTS: dict[str, MailjetEndpointConfig] = {
    "contact": MailjetEndpointConfig(
        name="contact",
        path="contact",
        partition_key="CreatedAt",
        sort="CreatedAt",
    ),
    "contactslist": MailjetEndpointConfig(
        name="contactslist",
        path="contactslist",
        partition_key="CreatedAt",
        sort="CreatedAt",
    ),
    "listrecipient": MailjetEndpointConfig(
        name="listrecipient",
        path="listrecipient",
    ),
    "campaign": MailjetEndpointConfig(
        name="campaign",
        path="campaign",
        partition_key="CreatedAt",
        sort="CreatedAt",
    ),
    "campaigndraft": MailjetEndpointConfig(
        name="campaigndraft",
        path="campaigndraft",
        partition_key="CreatedAt",
        # Mailjet rejects Sort=CreatedAt on campaigndraft ("Cannot sort on field createdat"),
        # so fall back to the monotonic ID for deterministic offset pagination.
        sort="ID",
    ),
    "message": MailjetEndpointConfig(
        name="message",
        path="message",
        partition_key="ArrivedAt",
        sort="ArrivedAt",
    ),
    "contactmetadata": MailjetEndpointConfig(
        name="contactmetadata",
        path="contactmetadata",
    ),
    "template": MailjetEndpointConfig(
        name="template",
        path="template",
    ),
    "openinformation": MailjetEndpointConfig(
        name="openinformation",
        path="openinformation",
        partition_key="OpenedAt",
        sort="OpenedAt",
        from_ts_field="OpenedAt",
        incremental_fields=[_datetime_incremental_field("OpenedAt")],
    ),
    "clickstatistics": MailjetEndpointConfig(
        name="clickstatistics",
        path="clickstatistics",
        partition_key="ClickedAt",
        sort="ClickedAt",
        from_ts_field="ClickedAt",
        incremental_fields=[_datetime_incremental_field("ClickedAt")],
    ),
}

# The Event API pushes per-recipient engagement and delivery events. Mailjet exposes no list
# endpoint for that stream — `/openinformation` and `/clickstatistics` cover opens and clicks
# only, under different field names — so these rows can only ever arrive by webhook, and they
# land in their own table rather than merging into a polled one.
WEBHOOK_TABLE_NAME = "messageevent"

# Every event type Mailjet's Event API can push. Each one is a separate `eventcallbackurl`
# registration; all of them feed the single `messageevent` table.
MAILJET_WEBHOOK_EVENTS: tuple[str, ...] = ("sent", "open", "click", "bounce", "blocked", "spam", "unsub")

WEBHOOK_SCHEMA_NAMES: frozenset[str] = frozenset({WEBHOOK_TABLE_NAME})

# Schema name -> the `schema_mapping` key the Hog template routes incoming events by.
SCHEMA_TO_WEBHOOK_RESOURCE: dict[str, str] = {WEBHOOK_TABLE_NAME: WEBHOOK_TABLE_NAME}

# Mailjet event payloads carry no event identifier, so the Hog template derives one by hashing
# the raw delivery body. Retries (Mailjet re-POSTs every 30s for up to 24h until it gets a 200)
# repeat the same body, so they collapse onto the same row.
WEBHOOK_PRIMARY_KEY = "event_id"

POLL_ENDPOINTS = tuple(MAILJET_ENDPOINTS.keys())

ENDPOINTS = (*POLL_ENDPOINTS, WEBHOOK_TABLE_NAME)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in MAILJET_ENDPOINTS.items()
}
# Webhook rows arrive as they happen, so there is no cursor to advance.
INCREMENTAL_FIELDS[WEBHOOK_TABLE_NAME] = []
