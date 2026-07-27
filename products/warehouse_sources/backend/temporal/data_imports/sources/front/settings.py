from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import PartitionFormat
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class FrontEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field to partition by (never a mutable field like updated_at).
    # Front timestamps are Unix epoch seconds (e.g. 1453770984.123), partitioned as datetime.
    partition_key: Optional[str] = None
    partition_format: PartitionFormat = "month"
    supports_incremental: bool = False
    # Per-page size. ``None`` means don't send a ``limit`` param (endpoint takes no query params).
    limit: Optional[int] = None
    sort_by: Optional[str] = None
    sort_order: Optional[str] = None  # "asc" / "desc"
    # ``q`` sub-property used as the server-side "after" time filter (e.g. "after" -> q[after]).
    # Only set where Front documents a genuine server-side timestamp filter.
    incremental_query_property: Optional[str] = None
    # Bound the first incremental sync to the last N days (None = full history).
    default_lookback_days: Optional[int] = None


def _datetime_incremental_field(field_name: str) -> IncrementalField:
    # Front timestamps are Unix epoch seconds, surfaced to users as a datetime cursor but
    # stored/compared as a numeric column (mirrors how Stripe handles its `created` field).
    return {
        "label": field_name,
        "type": IncrementalFieldType.DateTime,
        "field": field_name,
        "field_type": IncrementalFieldType.Integer,
    }


FRONT_ENDPOINTS: dict[str, FrontEndpointConfig] = {
    # Events expose a genuine server-side time filter via q[after]/q[before] (Unix seconds) and
    # are append-only, so this is the one incremental endpoint. Front caps the events page size
    # at 15. The initial sync is bounded to the last 365 days to avoid an unbounded backfill.
    "events": FrontEndpointConfig(
        name="events",
        path="/events",
        partition_key="emitted_at",
        partition_format="week",
        supports_incremental=True,
        limit=15,
        sort_by="created_at",
        sort_order="asc",
        incremental_query_property="after",
        default_lookback_days=365,
        incremental_fields=[_datetime_incremental_field("emitted_at")],
    ),
    # Contacts have no created_at/updated_at in the response object (only sortable server-side),
    # so we can't partition on a stable field. Full refresh.
    "contacts": FrontEndpointConfig(
        name="contacts",
        path="/contacts",
        limit=100,
        sort_by="created_at",
        sort_order="asc",
    ),
    # The list endpoint exposes no server-side time filter (only status filters), so full refresh.
    "conversations": FrontEndpointConfig(
        name="conversations",
        path="/conversations",
        partition_key="created_at",
        limit=100,
        sort_by="date",
        sort_order="asc",
    ),
    "accounts": FrontEndpointConfig(
        name="accounts",
        path="/accounts",
        partition_key="created_at",
        limit=100,
        sort_by="created_at",
        sort_order="asc",
    ),
    "tags": FrontEndpointConfig(
        name="tags",
        path="/tags",
        partition_key="created_at",
        limit=100,
        sort_by="id",
        sort_order="asc",
    ),
    # The remaining endpoints take no query params and have no stable creation timestamp in the
    # response, so they're plain full-refresh listings.
    "teammates": FrontEndpointConfig(name="teammates", path="/teammates"),
    "inboxes": FrontEndpointConfig(name="inboxes", path="/inboxes"),
    "channels": FrontEndpointConfig(name="channels", path="/channels"),
    "teams": FrontEndpointConfig(name="teams", path="/teams"),
}

ENDPOINTS = tuple(FRONT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FRONT_ENDPOINTS.items() if config.supports_incremental
}
