from dataclasses import dataclass, field


@dataclass
class TicketTailorEndpointConfig:
    name: str
    path: str
    # Ticket Tailor object ids are prefixed and globally unique within a box office
    # (e.g. "or_123", "it_456"), so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Ticket Tailor v1 top-level list endpoints. All are full refresh only: list endpoints paginate
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
}

ENDPOINTS = tuple(TICKET_TAILOR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
