from dataclasses import dataclass

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Recurly's API key authenticates to a single site; the host selects the data residency region.
RECURLY_BASE_URLS: dict[str, str] = {
    "us": "https://v3.recurly.com",
    "eu": "https://v3.eu.recurly.com",
}

# Every Recurly resource we sync carries a stable `created_at` we can partition on.
RECURLY_PARTITION_KEY = "created_at"


@dataclass
class RecurlyEndpoint:
    name: str
    path: str
    # `supports_incremental` is only `True` where the list endpoint exposes the
    # server-side `begin_time` filter (confirmed against the v2021-02-25 OpenAPI spec).
    # Endpoints that only accept `sort` (no time filter) stay full-refresh, since an
    # "incremental" sync would still read every page.
    supports_incremental: bool


RECURLY_ENDPOINTS: dict[str, RecurlyEndpoint] = {
    "accounts": RecurlyEndpoint("accounts", "/accounts", True),
    "acquisitions": RecurlyEndpoint("acquisitions", "/acquisitions", True),
    "add_ons": RecurlyEndpoint("add_ons", "/add_ons", True),
    "coupons": RecurlyEndpoint("coupons", "/coupons", True),
    "credit_payments": RecurlyEndpoint("credit_payments", "/credit_payments", True),
    "dunning_campaigns": RecurlyEndpoint("dunning_campaigns", "/dunning_campaigns", False),
    "external_subscriptions": RecurlyEndpoint("external_subscriptions", "/external_subscriptions", False),
    "gift_cards": RecurlyEndpoint("gift_cards", "/gift_cards", True),
    "invoices": RecurlyEndpoint("invoices", "/invoices", True),
    "items": RecurlyEndpoint("items", "/items", True),
    "line_items": RecurlyEndpoint("line_items", "/line_items", True),
    "measured_units": RecurlyEndpoint("measured_units", "/measured_units", True),
    "plans": RecurlyEndpoint("plans", "/plans", True),
    "shipping_methods": RecurlyEndpoint("shipping_methods", "/shipping_methods", True),
    "subscriptions": RecurlyEndpoint("subscriptions", "/subscriptions", True),
    "transactions": RecurlyEndpoint("transactions", "/transactions", True),
}

ENDPOINTS = tuple(RECURLY_ENDPOINTS.keys())


def _incremental_fields() -> list[IncrementalField]:
    return [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        },
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: (_incremental_fields() if endpoint.supports_incremental else [])
    for name, endpoint in RECURLY_ENDPOINTS.items()
}
