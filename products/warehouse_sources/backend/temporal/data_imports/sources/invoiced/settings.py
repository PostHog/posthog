from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class InvoicedEndpointConfig:
    path: str
    # Invoiced object IDs are unique per resource within an account (integers for documents,
    # user-assigned strings for catalog objects like items/plans/coupons), so `id` is a safe
    # primary key for every top-level list endpoint.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Invoiced REST API top-level list endpoints (https://developer.invoiced.com/api). Every one of
# these documents a server-side `updated_after` UNIX-timestamp filter, so `updated_at` is a
# genuine incremental cursor across the board.
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
    endpoint: [_UPDATED_AT_INCREMENTAL_FIELD] for endpoint in ENDPOINTS
}
