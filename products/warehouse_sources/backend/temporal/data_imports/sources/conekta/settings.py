from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://api.conekta.io"

# Conekta versions its API through the Accept header (`application/vnd.conekta-v<version>+json`)
# rather than a URL path segment, so the version label is sent on every request.
API_VERSION = "2.3.0"

# `limit` is capped at 250 across every list endpoint (the default is 20).
PAGE_SIZE = 250


def _epoch_incremental_field(name: str) -> IncrementalField:
    # Conekta timestamps are int64 seconds since the Unix epoch, so the stored cursor value is an
    # integer even though it means a point in time.
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.Integer,
    }


@dataclass(frozen=True)
class ConektaEndpointConfig:
    name: str
    path: str
    # Only `/orders` documents server-side timestamp filters (`created_at.gte` / `updated_at.gte`),
    # so it is the only endpoint that can sync incrementally. Everything else is full refresh:
    # paging the whole endpoint and dropping rows in Python would cost the same as a full sync.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation timestamp used for datetime partitioning. `None` for resources that expose
    # no creation timestamp at all (checkouts), which therefore stay unpartitioned.
    partition_key: str | None = "created_at"
    primary_keys: list[str] | None = field(default_factory=lambda: ["id"])
    # `/balance` answers with one object rather than a paginated list envelope.
    single_object: bool = False
    fanout: DependentEndpointConfig | None = None
    # Structural requirements of `FanoutEndpointLike` (see common/rest_source/fanout.py).
    default_incremental_field: str | None = None
    page_size: int = PAGE_SIZE


def _customer_fanout() -> DependentEndpointConfig:
    return DependentEndpointConfig(
        parent_name="customers",
        resolve_param="customer_id",
        resolve_field="id",
        include_from_parent=["id"],
        parent_field_renames={"id": "customer_id"},
        # A customer deleted between the parent listing and its child fetch answers 404.
        child_response_actions=[{"status_code": 404, "action": "ignore"}],
    )


CONEKTA_ENDPOINTS: dict[str, ConektaEndpointConfig] = {
    # The balance is a single point-in-time object with no id, so each full refresh replaces it.
    "balance": ConektaEndpointConfig(
        name="balance", path="/balance", partition_key=None, primary_keys=None, single_object=True
    ),
    "charges": ConektaEndpointConfig(name="charges", path="/charges"),
    # Payment links carry `starts_at` / `expires_at` but no creation timestamp.
    "checkouts": ConektaEndpointConfig(name="checkouts", path="/checkouts", partition_key=None),
    # Child companies of a holding company.
    "companies": ConektaEndpointConfig(name="companies", path="/companies"),
    "customers": ConektaEndpointConfig(name="customers", path="/customers"),
    "events": ConektaEndpointConfig(name="events", path="/events"),
    "orders": ConektaEndpointConfig(
        name="orders",
        path="/orders",
        incremental_fields=[_epoch_incremental_field("updated_at"), _epoch_incremental_field("created_at")],
    ),
    # Payment source and subscription ids are only documented per customer, so the customer id is
    # part of the key to keep it unique across the whole table.
    "payment_sources": ConektaEndpointConfig(
        name="payment_sources",
        path="/customers/{customer_id}/payment_sources",
        primary_keys=["customer_id", "id"],
        fanout=_customer_fanout(),
    ),
    "payout_orders": ConektaEndpointConfig(name="payout_orders", path="/payout_orders"),
    "plans": ConektaEndpointConfig(name="plans", path="/plans"),
    "subscriptions": ConektaEndpointConfig(
        name="subscriptions",
        path="/customers/{customer_id}/subscriptions",
        primary_keys=["customer_id", "id"],
        fanout=_customer_fanout(),
    ),
    "transactions": ConektaEndpointConfig(name="transactions", path="/transactions"),
    "transfers": ConektaEndpointConfig(name="transfers", path="/transfers"),
}

ENDPOINTS = tuple(CONEKTA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CONEKTA_ENDPOINTS.items() if config.incremental_fields
}

# Orders is merge-only: the `<field>.gte` filter is inclusive, so the watermark row comes back on
# every run and only a merge on `id` can dedupe it.
MERGE_ONLY_ENDPOINTS = ("orders",)
