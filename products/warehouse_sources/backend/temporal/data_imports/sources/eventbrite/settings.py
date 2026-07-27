from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


class EndpointScope(Enum):
    """How an endpoint is reached.

    - TOP_LEVEL: a single list endpoint, no parent needed.
    - ORG: fanned out per organization (path has an `{organization_id}` placeholder).
    - EVENT: fanned out per event (path has an `{event_id}` placeholder); events are
      themselves discovered per organization, so this is a two-level fan-out.
    """

    TOP_LEVEL = "top_level"
    ORG = "org"
    EVENT = "event"


@dataclass
class EventbriteEndpointConfig:
    name: str
    path: str
    data_key: str  # Key the list lives under in the JSON envelope, e.g. {"events": [...]}
    scope: EndpointScope
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_key: Optional[str] = None  # Stable created-style field for datetime partitioning
    # Resource change-timestamp field targeted by Eventbrite's server-side `changed_since` filter
    # (e.g. `changed`). When set, the endpoint supports true incremental sync; otherwise full refresh.
    changed_since_field: Optional[str] = None


def _changed_incremental_field() -> list[IncrementalField]:
    return [
        {
            "label": "changed",
            "type": IncrementalFieldType.DateTime,
            "field": "changed",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]


# Path to discover the organizations that own all org-scoped and event-scoped resources.
ORGANIZATIONS_PATH = "/users/me/organizations/"
ORG_EVENTS_PATH = "/organizations/{organization_id}/events/"


# Stream list cross-referenced against the Airbyte `source-eventbrite` connector (the canonical
# implementation). Only `orders` and `attendees` expose a documented server-side `changed_since`
# filter, so only those advertise incremental sync — everything else is full refresh.
EVENTBRITE_ENDPOINTS: dict[str, EventbriteEndpointConfig] = {
    "organizations": EventbriteEndpointConfig(
        name="organizations",
        path=ORGANIZATIONS_PATH,
        data_key="organizations",
        scope=EndpointScope.TOP_LEVEL,
        partition_key="created",
    ),
    "categories": EventbriteEndpointConfig(
        name="categories",
        path="/categories/",
        data_key="categories",
        scope=EndpointScope.TOP_LEVEL,
    ),
    "formats": EventbriteEndpointConfig(
        name="formats",
        path="/formats/",
        data_key="formats",
        scope=EndpointScope.TOP_LEVEL,
    ),
    "events": EventbriteEndpointConfig(
        name="events",
        path=ORG_EVENTS_PATH,
        data_key="events",
        scope=EndpointScope.ORG,
        partition_key="created",
    ),
    "venues": EventbriteEndpointConfig(
        name="venues",
        path="/organizations/{organization_id}/venues/",
        data_key="venues",
        scope=EndpointScope.ORG,
    ),
    "orders": EventbriteEndpointConfig(
        name="orders",
        path="/organizations/{organization_id}/orders/",
        data_key="orders",
        scope=EndpointScope.ORG,
        partition_key="created",
        changed_since_field="changed",
        incremental_fields=_changed_incremental_field(),
    ),
    "attendees": EventbriteEndpointConfig(
        name="attendees",
        path="/events/{event_id}/attendees/",
        data_key="attendees",
        scope=EndpointScope.EVENT,
        partition_key="created",
        changed_since_field="changed",
        incremental_fields=_changed_incremental_field(),
    ),
    "ticket_classes": EventbriteEndpointConfig(
        name="ticket_classes",
        path="/events/{event_id}/ticket_classes/",
        data_key="ticket_classes",
        scope=EndpointScope.EVENT,
    ),
}

ENDPOINTS = tuple(EVENTBRITE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in EVENTBRITE_ENDPOINTS.items()
}

INCREMENTAL_ENDPOINTS = tuple(name for name, config in EVENTBRITE_ENDPOINTS.items() if config.changed_since_field)
