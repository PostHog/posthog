from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class EventzillaEndpointConfig:
    name: str
    path: str  # May contain an `{event_id}` placeholder for fan-out endpoints.
    data_key: str  # Key wrapping the results array in the JSON response (e.g. "events").
    primary_keys: list[str]
    # Stable (never-updated) datetime field to partition by. Eventzilla exposes no `created_at`
    # on events/users, so only the purchase-time endpoints (attendees/transactions) get one.
    partition_key: Optional[str] = None
    # When True, `path` carries an `{event_id}` placeholder resolved by walking every event and
    # querying the child endpoint once per event. Child rows are stamped with `event_id`.
    fan_out_over_events: bool = False
    should_sync_default: bool = True
    # Eventzilla exposes no server-side updated-since / date-range filter on any endpoint — only
    # limit/offset paging (and status/category filters on /events) — so every table is full refresh.
    incremental_fields: list[IncrementalField] = field(default_factory=list)


EVENTZILLA_ENDPOINTS: dict[str, EventzillaEndpointConfig] = {
    "events": EventzillaEndpointConfig(
        name="events",
        path="/events",
        data_key="events",
        primary_keys=["id"],
    ),
    "categories": EventzillaEndpointConfig(
        name="categories",
        path="/categories",
        data_key="categories",
        # Categories are a static reference list; each item is only a `category` string.
        primary_keys=["category"],
    ),
    "users": EventzillaEndpointConfig(
        name="users",
        path="/users",
        data_key="users",
        primary_keys=["id"],
    ),
    "attendees": EventzillaEndpointConfig(
        name="attendees",
        path="/events/{event_id}/attendees",
        data_key="attendees",
        # Attendee `id` is unique per event, so include the parent event id to stay unique table-wide.
        primary_keys=["event_id", "id"],
        partition_key="transaction_date",
        fan_out_over_events=True,
    ),
    "transactions": EventzillaEndpointConfig(
        name="transactions",
        path="/events/{event_id}/transactions",
        data_key="transactions",
        primary_keys=["event_id", "checkout_id"],
        partition_key="transaction_date",
        fan_out_over_events=True,
    ),
    "tickets": EventzillaEndpointConfig(
        name="tickets",
        path="/events/{event_id}/tickets",
        data_key="tickets",
        primary_keys=["event_id", "id"],
        fan_out_over_events=True,
    ),
}

ENDPOINTS = tuple(EVENTZILLA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in EVENTZILLA_ENDPOINTS.items()
}
