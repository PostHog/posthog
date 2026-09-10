from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Elastic Email v4 caps each request at 1000 items and most list endpoints accept limit/offset.
# Use the max page size so we make as few round-trips as possible.
PAGE_SIZE = 1000


@dataclass
class ElasticEmailEndpointConfig:
    name: str
    path: str
    # Keys must be unique across the whole table. Most v4 resources are keyed by their natural name
    # (the value used in the resource's `/{name}` path); events have no single id so they use a composite.
    primary_keys: list[str]
    # A STABLE creation-style field used for datetime partitioning. Never a "last updated" field, which
    # would rewrite partitions on every sync. None when the resource exposes no stable date.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Append-only resources (immutable events) are synced with the incremental `from`/`to` time filter
    # but inserted rather than merged, since they have no reliably-unique primary key.
    append_only: bool = False
    # Static query params merged into every request for this endpoint (e.g. templates require `scopeType`,
    # events force ascending order so the watermark advances correctly).
    extra_params: dict[str, list[str] | str] = field(default_factory=dict)
    should_sync_default: bool = True


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


ELASTICEMAIL_ENDPOINTS: dict[str, ElasticEmailEndpointConfig] = {
    "contacts": ElasticEmailEndpointConfig(
        name="contacts",
        path="/contacts",
        primary_keys=["Email"],
        partition_key="DateAdded",
    ),
    "lists": ElasticEmailEndpointConfig(
        name="lists",
        path="/lists",
        primary_keys=["ListName"],
        partition_key="DateAdded",
    ),
    "segments": ElasticEmailEndpointConfig(
        name="segments",
        path="/segments",
        primary_keys=["Name"],
    ),
    "campaigns": ElasticEmailEndpointConfig(
        name="campaigns",
        path="/campaigns",
        primary_keys=["Name"],
    ),
    "templates": ElasticEmailEndpointConfig(
        name="templates",
        path="/templates",
        primary_keys=["Name"],
        partition_key="DateAdded",
        # scopeType is a required query param; request both visibility scopes so all templates are returned.
        extra_params={"scopeType": ["Personal", "Global"]},
    ),
    "events": ElasticEmailEndpointConfig(
        name="events",
        path="/events",
        # A transaction fans out into multiple event rows (Sent, Open, Click, ...); the only combination
        # that is unique per row is the message + event type + timestamp. Events carry no row id.
        primary_keys=["TransactionID", "MsgID", "EventType", "EventDate"],
        partition_key="EventDate",
        append_only=True,
        incremental_fields=[_datetime_incremental_field("EventDate")],
        # Default order is DateDescending; force ascending so rows arrive oldest-first and the
        # incremental watermark advances safely (sort_mode="asc").
        extra_params={"orderBy": "DateAscending"},
    ),
    "suppressions": ElasticEmailEndpointConfig(
        name="suppressions",
        path="/suppressions",
        primary_keys=["Email"],
    ),
}

ENDPOINTS = tuple(ELASTICEMAIL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ELASTICEMAIL_ENDPOINTS.items()
}
