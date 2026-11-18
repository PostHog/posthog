from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField

# List endpoints cap `limit` at 100; the largest page minimises round trips against the
# 5000 requests / 30 minutes rate limit.
PAGE_SIZE = 100


@dataclass(frozen=False)
class TicketTailorEndpointConfig:
    name: str
    path: str
    # Ticket Tailor object ids are prefixed and globally unique within a box office
    # (e.g. "or_123", "it_456"), so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # The stores list documents no `limit` parameter, so it is not sent there.
    sends_limit: bool = True
    fanout: Optional[DependentEndpointConfig] = None
    page_size: int = PAGE_SIZE
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None


# Ticket Tailor v1 list endpoints. All are full refresh only: list endpoints paginate
# newest-first by object id (`starting_after` cursor), and while some accept a server-side
# `created_at` filter, created-at windows never re-surface rows that were updated in place
# (orders and issued tickets mutate after creation). Ticket Tailor documents webhooks — which
# must be configured manually in its dashboard — as the only mechanism for update delivery, so
# there is no reliable incremental cursor to advance.
TICKET_TAILOR_ENDPOINTS: dict[str, TicketTailorEndpointConfig] = {
    "events": TicketTailorEndpointConfig(name="events", path="/v1/events"),
    "event_series": TicketTailorEndpointConfig(name="event_series", path="/v1/event_series"),
    "orders": TicketTailorEndpointConfig(name="orders", path="/v1/orders"),
    "issued_tickets": TicketTailorEndpointConfig(name="issued_tickets", path="/v1/issued_tickets"),
    "check_ins": TicketTailorEndpointConfig(name="check_ins", path="/v1/check_ins"),
    "discounts": TicketTailorEndpointConfig(name="discounts", path="/v1/discounts"),
    "products": TicketTailorEndpointConfig(name="products", path="/v1/products"),
    "vouchers": TicketTailorEndpointConfig(name="vouchers", path="/v1/vouchers"),
    "issued_memberships": TicketTailorEndpointConfig(name="issued_memberships", path="/v1/issued_memberships"),
    "membership_types": TicketTailorEndpointConfig(name="membership_types", path="/v1/membership_types"),
    # Holds accept an `updated_at.gte` filter, but rows carry `updated_at` as a nested object
    # ({"unix": ..., "iso": ...}), so there is no top-level column for the pipeline's watermark.
    "holds": TicketTailorEndpointConfig(name="holds", path="/v1/holds"),
    "stores": TicketTailorEndpointConfig(name="stores", path="/v1/stores", sends_limit=False),
    "voucher_codes": TicketTailorEndpointConfig(
        name="voucher_codes",
        path="/v1/vouchers/{voucher_id}/codes",
        primary_keys=["voucher_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="vouchers",
            resolve_param="voucher_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "voucher_id"},
            # A voucher deleted between the voucher listing and its codes request returns 404.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "waitlist_signups": TicketTailorEndpointConfig(
        name="waitlist_signups",
        path="/v1/event_series/{event_series_id}/waitlist_signups",
        # Signup rows name their event occurrence but not the series, so the series id comes from the parent.
        primary_keys=["event_series_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="event_series",
            resolve_param="event_series_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "event_series_id"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
}

ENDPOINTS = tuple(TICKET_TAILOR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
