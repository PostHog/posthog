from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.fourthwall.com"

# Fourthwall's list endpoints take a 0-based `page` and a `size`. The docs give a default of 20
# and document no maximum, so 100 cuts the request count without relying on an undocumented cap.
# No endpoint takes a sort parameter, so a row inserted while a full walk is in progress can shift
# the offsets; a full-refresh sync would miss it and pick it up on the next run.
PAGE_SIZE = 100


@dataclass
class FourthwallEndpointConfig:
    name: str
    # Path below `/open-api/{version}`; the version segment comes from the source's pin.
    path: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Server-side lower-bound filter that matches `incremental_fields`, e.g. `updatedAt[gt]`.
    incremental_param: str | None = None
    partition_key: str | None = None
    primary_key: list[str] = field(default_factory=lambda: ["id"])
    # Most endpoints wrap rows in a `{results, total, page, size, totalPages}` envelope; a few
    # return a bare JSON array with no pagination at all.
    paginated: bool = True
    sort_mode: Literal["asc", "desc"] = "asc"
    # Webhook event types whose payload carries this table's row.
    webhook_events: tuple[str, ...] = ()


FOURTHWALL_ENDPOINTS: dict[str, FourthwallEndpointConfig] = {
    "orders": FourthwallEndpointConfig(
        name="orders",
        path="/order",
        # `updatedAt[gt]` is a real server-side filter and it rides every page (only `page`
        # changes between requests), so an incremental sync fetches fewer pages rather than
        # just changing the write disposition.
        incremental_fields=[incremental_field("updatedAt")],
        incremental_param="updatedAt[gt]",
        partition_key="createdAt",
        # Fourthwall documents no ordering for the orders list and offers no sort parameter, so
        # we cannot claim rows arrive oldest-first. `desc` makes the pipeline finalize the
        # watermark only after a fully successful sync, so a partial run can't advance it past
        # orders it never fetched.
        sort_mode="desc",
        webhook_events=("ORDER_PLACED", "ORDER_UPDATED"),
    ),
    "products": FourthwallEndpointConfig(
        name="products",
        path="/products",
        # The products list only filters by `search`, so there is no server-side timestamp
        # filter to sync incrementally against.
        partition_key="createdAt",
    ),
    "collections": FourthwallEndpointConfig(
        name="collections",
        path="/collections",
    ),
    "donations": FourthwallEndpointConfig(
        name="donations",
        path="/donations",
        partition_key="createdAt",
        webhook_events=("DONATION",),
    ),
    "members": FourthwallEndpointConfig(
        name="members",
        path="/memberships/members",
        partition_key="createdAt",
        webhook_events=("SUBSCRIPTION_PURCHASED", "SUBSCRIPTION_CHANGED", "SUBSCRIPTION_EXPIRED"),
    ),
    "membership_tiers": FourthwallEndpointConfig(
        name="membership_tiers",
        path="/memberships/tiers",
        # Returns a bare array of tiers with no pagination parameters.
        paginated=False,
    ),
    "promotions": FourthwallEndpointConfig(
        name="promotions",
        path="/promotions",
    ),
    "mailing_list_entries": FourthwallEndpointConfig(
        name="mailing_list_entries",
        path="/mailing-list-entries",
    ),
}

ENDPOINTS = tuple(FOURTHWALL_ENDPOINTS)

INCREMENTAL_ENDPOINTS = tuple(name for name, config in FOURTHWALL_ENDPOINTS.items() if config.incremental_fields)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FOURTHWALL_ENDPOINTS.items() if config.incremental_fields
}

# Only these tables are offered webhook sync: their event set covers the resource's whole
# mutation surface and each event's `data` is the same object the list endpoint returns.
# Product, collection and promotion events exist too, but their update payloads nest the
# object under a differently shaped wrapper we cannot map without a live sample, so those
# tables stay on polling.
SCHEMA_TO_WEBHOOK_EVENTS: dict[str, list[str]] = {
    name: list(config.webhook_events) for name, config in FOURTHWALL_ENDPOINTS.items() if config.webhook_events
}

WEBHOOK_SCHEMA_NAMES = tuple(SCHEMA_TO_WEBHOOK_EVENTS)

ALL_WEBHOOK_EVENTS = sorted({event for events in SCHEMA_TO_WEBHOOK_EVENTS.values() for event in events})

# Schema name -> the `schema_mapping` key incoming deliveries are routed by. Several event types
# feed one table, so the hog template collapses the event type to this resource key first.
SCHEMA_TO_WEBHOOK_RESOURCE: dict[str, str] = {
    "orders": "order",
    "donations": "donation",
    "members": "member",
}

WEBHOOK_EVENT_TO_RESOURCE: dict[str, str] = {
    event: SCHEMA_TO_WEBHOOK_RESOURCE[name] for name, events in SCHEMA_TO_WEBHOOK_EVENTS.items() for event in events
}

# ORDER_UPDATED wraps the order under `data.order` (the rest of the events we subscribe to put
# the object straight in `data`), so webhook rows need unwrapping before they can merge onto the
# table the pull path fills.
WEBHOOK_EVENT_DATA_UNWRAP_KEY: dict[str, str] = {"ORDER_UPDATED": "order"}
