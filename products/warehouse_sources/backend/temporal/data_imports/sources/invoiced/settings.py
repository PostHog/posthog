from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
class InvoicedEndpointConfig:
    path: str
    # Invoiced object IDs are unique per resource within an account (integers for documents,
    # user-assigned strings for catalog objects like items/plans/coupons), so `id` is a safe
    # primary key for every top-level list endpoint.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Endpoints that document the server-side `updated_after` filter can sync incrementally.
    supports_updated_after: bool = True
    # Sent as `sort`; None for endpoints whose docs list no `sort` parameter.
    sort: str | None = "updated_at asc"


# Invoiced REST API top-level list endpoints (https://developer.invoiced.com/api). Endpoints that
# document a server-side `updated_after` UNIX-timestamp filter use `updated_at` as an incremental
# cursor; the rest are full refresh only.
INVOICED_ENDPOINTS: dict[str, InvoicedEndpointConfig] = {
    "customers": InvoicedEndpointConfig(path="/customers"),
    "invoices": InvoicedEndpointConfig(path="/invoices"),
    "payments": InvoicedEndpointConfig(path="/payments"),
    "credit_notes": InvoicedEndpointConfig(path="/credit_notes"),
    "estimates": InvoicedEndpointConfig(path="/estimates"),
    "subscriptions": InvoicedEndpointConfig(path="/subscriptions"),
    "items": InvoicedEndpointConfig(path="/items"),
    "plans": InvoicedEndpointConfig(path="/plans"),
    "coupons": InvoicedEndpointConfig(path="/coupons"),
    "tax_rates": InvoicedEndpointConfig(path="/tax_rates"),
    # Documents only `sort` and `filter`.
    "tasks": InvoicedEndpointConfig(path="/tasks", supports_updated_after=False),
    # Documents no list query parameters.
    "credit_balance_adjustments": InvoicedEndpointConfig(
        path="/credit_balance_adjustments", supports_updated_after=False, sort=None
    ),
    # Events are immutable (no `updated_at`) and the list documents only a `related_to` filter.
    "events": InvoicedEndpointConfig(path="/events", supports_updated_after=False, sort=None),
}

ENDPOINTS = tuple(INVOICED_ENDPOINTS.keys())

# Invoiced represents timestamps as UNIX epoch integers (`updated_at` in responses,
# `updated_after` as the matching request filter).
_UPDATED_AT_INCREMENTAL_FIELD: IncrementalField = {
    "label": "updated_at",
    "type": IncrementalFieldType.Integer,
    "field": "updated_at",
    "field_type": IncrementalFieldType.Integer,
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    endpoint: [_UPDATED_AT_INCREMENTAL_FIELD] if config.supports_updated_after else []
    for endpoint, config in INVOICED_ENDPOINTS.items()
}
