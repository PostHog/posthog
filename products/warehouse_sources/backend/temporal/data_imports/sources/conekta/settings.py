from dataclasses import dataclass, field

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


@dataclass
class ConektaEndpointConfig:
    path: str
    # Only `/orders` documents server-side timestamp filters (`created_at.gte` / `updated_at.gte`),
    # so it is the only endpoint that can sync incrementally. Everything else is full refresh:
    # paging the whole endpoint and dropping rows in Python would cost the same as a full sync.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation timestamp used for datetime partitioning. `None` for resources that expose
    # no creation timestamp at all (checkouts), which therefore stay unpartitioned.
    partition_key: str | None = "created_at"


CONEKTA_ENDPOINTS: dict[str, ConektaEndpointConfig] = {
    "charges": ConektaEndpointConfig(path="/charges"),
    # Payment links carry `starts_at` / `expires_at` but no creation timestamp.
    "checkouts": ConektaEndpointConfig(path="/checkouts", partition_key=None),
    "customers": ConektaEndpointConfig(path="/customers"),
    "events": ConektaEndpointConfig(path="/events"),
    "orders": ConektaEndpointConfig(
        path="/orders",
        incremental_fields=[_epoch_incremental_field("updated_at"), _epoch_incremental_field("created_at")],
    ),
    "payout_orders": ConektaEndpointConfig(path="/payout_orders"),
    "plans": ConektaEndpointConfig(path="/plans"),
    "transactions": ConektaEndpointConfig(path="/transactions"),
    "transfers": ConektaEndpointConfig(path="/transfers"),
}

ENDPOINTS = tuple(CONEKTA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CONEKTA_ENDPOINTS.items() if config.incremental_fields
}

# Orders is merge-only: the `<field>.gte` filter is inclusive, so the watermark row comes back on
# every run and only a merge on `id` can dedupe it.
MERGE_ONLY_ENDPOINTS = ("orders",)
