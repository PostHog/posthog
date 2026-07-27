from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

ORB_API_BASE_URL = "https://api.withorb.com/v1"

# Orb caps list endpoints at 100 items per page (default 20).
DEFAULT_PAGE_SIZE = 100


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class OrbEndpointConfig:
    name: str
    path: str
    table_name: str
    # Query-param key for the server-side "strictly greater than" timestamp filter used for
    # incremental syncs (e.g. "created_at[gt]"). None => the endpoint has no server-side time
    # filter, so it is full-refresh only.
    incremental_param: Optional[str] = None
    # Object field the incremental_param filters on (e.g. "created_at"). Drives INCREMENTAL_FIELDS.
    incremental_field: Optional[str] = None
    # Stable datetime field to partition by. Must never change after creation, so always a
    # creation-style field (created_at), never a mutable one.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Top-level Orb list endpoints. All return `{"data": [...], "pagination_metadata": {...}}`, are
# cursor-paginated, and sort newest-first by creation time. Incremental endpoints expose a
# server-side `<field>[gt]` timestamp filter; the rest are full-refresh only.
#
# Invoices is the odd one out: it has no `created_at` filter, only `invoice_date[gt]`, so its
# incremental cursor is `invoice_date` while it still partitions on the stable `created_at`.
ORB_ENDPOINTS: dict[str, OrbEndpointConfig] = {
    "Customers": OrbEndpointConfig(
        name="Customers",
        path="/customers",
        table_name="customers",
        incremental_param="created_at[gt]",
        incremental_field="created_at",
        partition_key="created_at",
    ),
    "Plans": OrbEndpointConfig(
        name="Plans",
        path="/plans",
        table_name="plans",
        incremental_param="created_at[gt]",
        incremental_field="created_at",
        partition_key="created_at",
    ),
    "Subscriptions": OrbEndpointConfig(
        name="Subscriptions",
        path="/subscriptions",
        table_name="subscriptions",
        incremental_param="created_at[gt]",
        incremental_field="created_at",
        partition_key="created_at",
    ),
    "Invoices": OrbEndpointConfig(
        name="Invoices",
        path="/invoices",
        table_name="invoices",
        incremental_param="invoice_date[gt]",
        incremental_field="invoice_date",
        partition_key="created_at",
    ),
    "CreditNotes": OrbEndpointConfig(
        name="CreditNotes",
        path="/credit_notes",
        table_name="credit_notes",
        incremental_param="created_at[gt]",
        incremental_field="created_at",
        partition_key="created_at",
    ),
    "Items": OrbEndpointConfig(
        name="Items",
        path="/items",
        table_name="items",
        partition_key="created_at",
    ),
    "Coupons": OrbEndpointConfig(
        name="Coupons",
        path="/coupons",
        table_name="coupons",
    ),
}

ENDPOINTS = tuple(ORB_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [_datetime_field(cfg.incremental_field)]
    for name, cfg in ORB_ENDPOINTS.items()
    if cfg.incremental_field is not None
}
