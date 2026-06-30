from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField

# Number of records to request per page. Lago caps `per_page` at 100.
DEFAULT_PAGE_SIZE = 100


@dataclass
class LagoEndpointConfig:
    name: str
    # Path appended to the API base (which already ends in `/api/v1`).
    path: str
    # Key under which the list of records lives in the JSON response body
    # (e.g. `{"customers": [...], "meta": {...}}`).
    data_key: str
    # Lago objects carry both an external (customer-supplied) id and `lago_id`, Lago's own
    # globally-unique UUID. `lago_id` is the stable primary key across every resource.
    primary_key: str = "lago_id"
    # Stable, immutable field to partition by. `created_at` is present on every list resource
    # and never changes. Never partition on a mutable field.
    partition_key: Optional[str] = "created_at"
    page_size: int = DEFAULT_PAGE_SIZE
    # Lago's REST API exposes no universal server-side `created_at`/`updated_at` cursor, so every
    # stream is full-refresh only. Left empty deliberately — see the module docstring in lago.py.
    incremental_fields: list[IncrementalField] = field(default_factory=list)


# Top-level list endpoints that return a full collection without requiring a parent resource
# (e.g. a customer or subscription id) as a filter. Per-customer resources such as `wallets` and
# `wallet_transactions`, and the write-oriented `events` endpoint, are intentionally excluded:
# they require a fan-out we cannot verify against the live API without credentials.
LAGO_ENDPOINTS: dict[str, LagoEndpointConfig] = {
    "add_ons": LagoEndpointConfig(name="add_ons", path="/add_ons", data_key="add_ons"),
    "applied_coupons": LagoEndpointConfig(name="applied_coupons", path="/applied_coupons", data_key="applied_coupons"),
    "billable_metrics": LagoEndpointConfig(
        name="billable_metrics", path="/billable_metrics", data_key="billable_metrics"
    ),
    "coupons": LagoEndpointConfig(name="coupons", path="/coupons", data_key="coupons"),
    "credit_notes": LagoEndpointConfig(name="credit_notes", path="/credit_notes", data_key="credit_notes"),
    "customers": LagoEndpointConfig(name="customers", path="/customers", data_key="customers"),
    "fees": LagoEndpointConfig(name="fees", path="/fees", data_key="fees"),
    "invoices": LagoEndpointConfig(name="invoices", path="/invoices", data_key="invoices"),
    "plans": LagoEndpointConfig(name="plans", path="/plans", data_key="plans"),
    "subscriptions": LagoEndpointConfig(name="subscriptions", path="/subscriptions", data_key="subscriptions"),
}

ENDPOINTS = tuple(LAGO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LAGO_ENDPOINTS.items()
}
