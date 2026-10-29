from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
class PersistiqEndpointConfig:
    name: str
    path: str
    # PersistIQ wraps each list response in a key named after the resource
    # (e.g. `{"leads": [...], "has_more": ..., "next_page": ...}`), so the row list
    # key varies per endpoint and is stored here.
    list_key: str
    # PersistIQ object IDs are globally unique within an account, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # `lead_statuses` and `lead_fields` return the whole collection in one response with no `has_more`.
    paginated: bool = True
    # Query param that filters rows to those after a timestamp; only `events` has one (`start_at`).
    incremental_param: Optional[str] = None
    partition_key: Optional[str] = None


# PersistIQ REST API list endpoints. Only `events` takes a server-side time filter (`start_at`); the
# others expose no `updated_after`-style filter, so they are full refresh (a client-side scan of every
# page would cost the same as a full refresh).
PERSISTIQ_ENDPOINTS: dict[str, PersistiqEndpointConfig] = {
    "leads": PersistiqEndpointConfig(name="leads", path="/leads", list_key="leads"),
    "users": PersistiqEndpointConfig(name="users", path="/users", list_key="users"),
    "campaigns": PersistiqEndpointConfig(name="campaigns", path="/campaigns", list_key="campaigns"),
    "events": PersistiqEndpointConfig(
        name="events", path="/events", list_key="events", incremental_param="start_at", partition_key="event_at"
    ),
    "lead_statuses": PersistiqEndpointConfig(
        name="lead_statuses", path="/lead_statuses", list_key="lead_statuses", paginated=False
    ),
    "lead_fields": PersistiqEndpointConfig(
        name="lead_fields", path="/lead_fields", list_key="lead_fields", paginated=False
    ),
    "dnc_domains": PersistiqEndpointConfig(name="dnc_domains", path="/dnc_domains", list_key="dnc_domains"),
}

ENDPOINTS = tuple(PERSISTIQ_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "events": [
        IncrementalField(
            label="event_at",
            type=IncrementalFieldType.DateTime,
            field="event_at",
            field_type=IncrementalFieldType.DateTime,
        )
    ],
}
