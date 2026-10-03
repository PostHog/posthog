from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)

# The list endpoints accept pageSize 1..100; 100 minimises round trips.
PAGE_SIZE = 100


@dataclass(frozen=True)
class HumanitixEndpointConfig:
    name: str
    path: str
    # Key of the row array in the paginated response envelope; it differs per endpoint
    # (e.g. `events` for /events, `tags` for /tags) even though the envelope shape is identical.
    list_key: str
    # Humanitix objects are Mongo documents, so `_id` is a stable, globally unique primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["_id"])
    # A stable (never-rewritten) datetime field to partition by.
    partition_key: Optional[str] = None
    # Set for endpoints nested under a parent resource, fetched once per parent row.
    fanout: Optional[DependentEndpointConfig] = None
    # Read by the shared fan-out builder. Every endpoint is full refresh, so no incremental fields.
    incremental_fields: list[Any] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    page_size: int = PAGE_SIZE


# Orders and tickets are only listed per event. Fan out over `/events` and stamp the parent event id
# onto each row, so `eventId` is always present (it is optional on orders) and scopes the key.
_EVENT_FANOUT = DependentEndpointConfig(
    parent_name="events",
    resolve_param="eventId",
    resolve_field="_id",
    include_from_parent=["_id"],
    parent_field_renames={"_id": "eventId"},
)


# Humanitix Public API list endpoints. `/events` and `/tags` are account-scoped top-level lists;
# orders and tickets fan out per event. The `/global/*` endpoints return the public marketplace
# catalog rather than the account's own data, so they are not exposed here.
# All are full refresh only. Orders and tickets accept a `since` filter, but the API does not say
# which timestamp it compares, so a cursor on `updatedAt` could silently miss refunds and cancellations.
HUMANITIX_ENDPOINTS: dict[str, HumanitixEndpointConfig] = {
    "events": HumanitixEndpointConfig(name="events", path="/events", list_key="events"),
    "tags": HumanitixEndpointConfig(name="tags", path="/tags", list_key="tags"),
    "orders": HumanitixEndpointConfig(
        name="orders",
        path="/events/{eventId}/orders",
        list_key="orders",
        primary_keys=["eventId", "_id"],
        partition_key="createdAt",
        fanout=_EVENT_FANOUT,
    ),
    "tickets": HumanitixEndpointConfig(
        name="tickets",
        path="/events/{eventId}/tickets",
        list_key="tickets",
        primary_keys=["eventId", "_id"],
        partition_key="createdAt",
        fanout=_EVENT_FANOUT,
    ),
}

ENDPOINTS = tuple(HUMANITIX_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list] = {}
