from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


class EndpointScope(Enum):
    """How an endpoint is reached.

    - ORGANIZER: a single organizer-scoped list endpoint, no fan-out needed.
    - EVENT: fanned out per event (path has an `{event}` placeholder); events are
      discovered from the organizer-level events list first.
    """

    ORGANIZER = "organizer"
    EVENT = "event"


@dataclass
class PretixEndpointConfig:
    name: str
    path: str
    scope: EndpointScope
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable created-style datetime field for partitioning. Never a last-modified field.
    partition_key: Optional[str] = None
    # When set, the endpoint supports pretix's server-side `modified_since` filter targeting
    # this resource field (true incremental sync); otherwise the stream is full refresh only.
    modified_since_field: Optional[str] = None
    # Explicit `ordering` value to request. Only set where the docs list it as a valid
    # ordering field for that endpoint — pretix rejects unknown ordering values.
    ordering: Optional[str] = None


def _last_modified_incremental_field() -> list[IncrementalField]:
    return [
        {
            "label": "last_modified",
            "type": IncrementalFieldType.DateTime,
            "field": "last_modified",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]


EVENTS_PATH = "/organizers/{organizer}/events/"

# Column injected into every event-scoped (fan-out) row so composite primary keys stay unique
# across the whole table — pretix docs don't guarantee child ids are unique beyond their event.
EVENT_SLUG_KEY = "event_slug"


# Stream list cross-referenced against the Airbyte `source-pretix` connector plus the official API
# docs. `orders` is the only stream with a documented server-side timestamp filter
# (`modified_since`, orderable by `last_modified`), so it is the only incremental stream — every
# other list endpoint is full refresh. `orders` and `invoices` use the organizer-level endpoints
# (added in pretix 2023.8) that span all events and stamp each row with its parent `event` slug,
# avoiding a per-event fan-out for the two largest tables. Order positions arrive embedded in each
# order's `positions` array, so they don't need a dedicated stream.
PRETIX_ENDPOINTS: dict[str, PretixEndpointConfig] = {
    "events": PretixEndpointConfig(
        name="events",
        path=EVENTS_PATH,
        scope=EndpointScope.ORGANIZER,
        # Event slugs are unique within an organizer, and a source is scoped to one organizer.
        primary_keys=["slug"],
    ),
    "orders": PretixEndpointConfig(
        name="orders",
        path="/organizers/{organizer}/orders/",
        scope=EndpointScope.ORGANIZER,
        # Order codes are only documented unique within their event; rows carry the event slug.
        primary_keys=["event", "code"],
        incremental_fields=_last_modified_incremental_field(),
        partition_key="datetime",
        modified_since_field="last_modified",
        ordering="last_modified",
    ),
    "invoices": PretixEndpointConfig(
        name="invoices",
        path="/organizers/{organizer}/invoices/",
        scope=EndpointScope.ORGANIZER,
        # Invoice numbers are prefixed per event; rows carry the event slug.
        primary_keys=["event", "number"],
    ),
    "customers": PretixEndpointConfig(
        name="customers",
        path="/organizers/{organizer}/customers/",
        scope=EndpointScope.ORGANIZER,
        primary_keys=["identifier"],
    ),
    "gift_cards": PretixEndpointConfig(
        name="gift_cards",
        path="/organizers/{organizer}/giftcards/",
        scope=EndpointScope.ORGANIZER,
    ),
    "subevents": PretixEndpointConfig(
        name="subevents",
        path="/organizers/{organizer}/events/{event}/subevents/",
        scope=EndpointScope.EVENT,
        primary_keys=[EVENT_SLUG_KEY, "id"],
    ),
    "items": PretixEndpointConfig(
        name="items",
        path="/organizers/{organizer}/events/{event}/items/",
        scope=EndpointScope.EVENT,
        primary_keys=[EVENT_SLUG_KEY, "id"],
        ordering="id",
    ),
    "categories": PretixEndpointConfig(
        name="categories",
        path="/organizers/{organizer}/events/{event}/categories/",
        scope=EndpointScope.EVENT,
        primary_keys=[EVENT_SLUG_KEY, "id"],
    ),
    "questions": PretixEndpointConfig(
        name="questions",
        path="/organizers/{organizer}/events/{event}/questions/",
        scope=EndpointScope.EVENT,
        primary_keys=[EVENT_SLUG_KEY, "id"],
    ),
    "quotas": PretixEndpointConfig(
        name="quotas",
        path="/organizers/{organizer}/events/{event}/quotas/",
        scope=EndpointScope.EVENT,
        primary_keys=[EVENT_SLUG_KEY, "id"],
        ordering="id",
    ),
    "vouchers": PretixEndpointConfig(
        name="vouchers",
        path="/organizers/{organizer}/events/{event}/vouchers/",
        scope=EndpointScope.EVENT,
        primary_keys=[EVENT_SLUG_KEY, "id"],
        ordering="id",
    ),
    "checkin_lists": PretixEndpointConfig(
        name="checkin_lists",
        path="/organizers/{organizer}/events/{event}/checkinlists/",
        scope=EndpointScope.EVENT,
        primary_keys=[EVENT_SLUG_KEY, "id"],
        ordering="id",
    ),
    "waiting_list_entries": PretixEndpointConfig(
        name="waiting_list_entries",
        path="/organizers/{organizer}/events/{event}/waitinglistentries/",
        scope=EndpointScope.EVENT,
        primary_keys=[EVENT_SLUG_KEY, "id"],
    ),
    "tax_rules": PretixEndpointConfig(
        name="tax_rules",
        path="/organizers/{organizer}/events/{event}/taxrules/",
        scope=EndpointScope.EVENT,
        primary_keys=[EVENT_SLUG_KEY, "id"],
    ),
}

ENDPOINTS = tuple(PRETIX_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PRETIX_ENDPOINTS.items()
}

INCREMENTAL_ENDPOINTS = tuple(name for name, config in PRETIX_ENDPOINTS.items() if config.modified_since_field)
