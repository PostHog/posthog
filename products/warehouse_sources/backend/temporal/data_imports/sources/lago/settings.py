from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# Number of records to request per page. Lago caps `per_page` at 100.
DEFAULT_PAGE_SIZE = 100


@dataclass(frozen=True)
class LagoEndpointConfig:
    name: str
    # Path appended to the API base (which already ends in `/api/v1`).
    path: str
    # Key under which the list of records lives in the JSON response body
    # (e.g. `{"customers": [...], "meta": {...}}`).
    data_key: str
    # Lago objects carry both an external (customer-supplied) id and `lago_id`, Lago's own
    # globally-unique UUID. `lago_id` is the stable primary key on every resource except events.
    primary_keys: list[str] = field(default_factory=lambda: ["lago_id"])
    # Stable, immutable field to partition by. `created_at` is present on every list resource
    # and never changes. Never partition on a mutable field.
    partition_key: Optional[str] = "created_at"
    page_size: int = DEFAULT_PAGE_SIZE
    # Lago's REST API exposes no universal server-side `created_at`/`updated_at` cursor, so every
    # stream is full-refresh only. Left empty deliberately — see the module docstring in lago.py.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    # Set for resources only listed per parent (e.g. a plan's charges); the parent is re-listed each sync.
    fanout: Optional[DependentEndpointConfig] = None


# Charge filters are not a separate table: every charge row already carries its `filters` array.
LAGO_ENDPOINTS: dict[str, LagoEndpointConfig] = {
    "add_ons": LagoEndpointConfig(name="add_ons", path="/add_ons", data_key="add_ons"),
    "applied_coupons": LagoEndpointConfig(name="applied_coupons", path="/applied_coupons", data_key="applied_coupons"),
    "billable_metrics": LagoEndpointConfig(
        name="billable_metrics", path="/billable_metrics", data_key="billable_metrics"
    ),
    "coupons": LagoEndpointConfig(name="coupons", path="/coupons", data_key="coupons"),
    "credit_notes": LagoEndpointConfig(name="credit_notes", path="/credit_notes", data_key="credit_notes"),
    "charges": LagoEndpointConfig(
        name="charges",
        path="/plans/{plan_code}/charges",
        data_key="charges",
        fanout=DependentEndpointConfig(
            parent_name="plans",
            resolve_param="plan_code",
            # Plan codes are user-defined, so the path segment is the percent-encoded code that
            # `_encode_plan_code` adds to each plan row.
            resolve_field="_path_code",
            include_from_parent=["lago_id", "code"],
            parent_field_renames={"lago_id": "lago_plan_id", "code": "plan_code"},
        ),
    ),
    "customers": LagoEndpointConfig(name="customers", path="/customers", data_key="customers"),
    # Lago events have no guaranteed `lago_id`. Lago dedupes an event on its transaction id within a
    # subscription, and the ClickHouse event store also keys on the timestamp.
    "events": LagoEndpointConfig(
        name="events",
        path="/events",
        data_key="events",
        primary_keys=["transaction_id", "external_subscription_id", "timestamp"],
        partition_key="timestamp",
    ),
    "fees": LagoEndpointConfig(name="fees", path="/fees", data_key="fees"),
    "invoices": LagoEndpointConfig(name="invoices", path="/invoices", data_key="invoices"),
    "payments": LagoEndpointConfig(name="payments", path="/payments", data_key="payments"),
    "plans": LagoEndpointConfig(name="plans", path="/plans", data_key="plans"),
    "subscriptions": LagoEndpointConfig(name="subscriptions", path="/subscriptions", data_key="subscriptions"),
    # `/wallet_transactions` only accepts POST (top-ups); the listing is per wallet.
    "wallet_transactions": LagoEndpointConfig(
        name="wallet_transactions",
        path="/wallets/{wallet_id}/wallet_transactions",
        data_key="wallet_transactions",
        fanout=DependentEndpointConfig(
            parent_name="wallets",
            resolve_param="wallet_id",
            resolve_field="lago_id",
            include_from_parent=["external_customer_id"],
            parent_field_renames={"external_customer_id": "external_customer_id"},
        ),
    ),
    "wallets": LagoEndpointConfig(name="wallets", path="/wallets", data_key="wallets"),
}

ENDPOINTS = tuple(LAGO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LAGO_ENDPOINTS.items()
}
