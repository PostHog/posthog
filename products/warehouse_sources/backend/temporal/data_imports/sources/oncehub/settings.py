from dataclasses import dataclass, field
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)

# List endpoints accept a `limit` of 1-100 (default 10); the largest page minimises round trips
# against OnceHub's tight 5 requests/second account rate limit.
PAGE_SIZE = 100


@dataclass(frozen=True)
class OncehubEndpointConfig:
    name: str
    path: str
    # OnceHub object IDs are prefixed strings (BKNG-, CTC-, USR-, TM-, BKC-, MP-, ...) that are
    # unique across the account, so `id` is a safe primary key for every list endpoint.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    page_size: int = PAGE_SIZE
    incremental_fields: list[Any] = field(default_factory=list)
    default_incremental_field: str | None = None
    fanout: DependentEndpointConfig | None = None


# OnceHub v2 list endpoints, from both the Booking Calendars API and the classic Booking Pages API
# (event types, booking pages, master pages), which share one base URL and API key. All are full refresh only: the API's
# `last_updated_time.gt` filters are date-granular and list results paginate by object-ID cursor
# in reverse-chronological order, so there is no reliable server-side incremental cursor to
# advance safely without verified ordering guarantees.
ONCEHUB_ENDPOINTS: dict[str, OncehubEndpointConfig] = {
    "bookings": OncehubEndpointConfig(name="bookings", path="/bookings"),
    "booking_calendars": OncehubEndpointConfig(name="booking_calendars", path="/booking-calendars"),
    "contacts": OncehubEndpointConfig(name="contacts", path="/contacts"),
    "users": OncehubEndpointConfig(name="users", path="/users"),
    "teams": OncehubEndpointConfig(name="teams", path="/teams"),
    "event_types": OncehubEndpointConfig(name="event_types", path="/event-types"),
    "booking_pages": OncehubEndpointConfig(name="booking_pages", path="/booking-pages"),
    "master_pages": OncehubEndpointConfig(name="master_pages", path="/master-pages"),
    # One availability object per user, which carries no ID of its own, so the parent user ID keys it.
    "user_scheduling_availability": OncehubEndpointConfig(
        name="user_scheduling_availability",
        path="/users/{id}/scheduling-availability",
        primary_keys=["user_id"],
        fanout=DependentEndpointConfig(
            parent_name="users",
            resolve_param="id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "user_id"},
            parent_params={"limit": PAGE_SIZE},
            # A user deleted between the users listing and this fetch 404s; skip it instead of failing the sync.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
}

ENDPOINTS = tuple(ONCEHUB_ENDPOINTS.keys())
