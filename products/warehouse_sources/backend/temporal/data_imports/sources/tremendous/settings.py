from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class TremendousEndpointConfig:
    path: str
    # Top-level key the list of records is nested under in the response body (e.g. {"orders": [...]}).
    data_key: str
    # Endpoints without offset/limit params return the whole collection in one response.
    paginated: bool = False
    page_size: int = 500
    # Stable creation timestamp used for datetime partitioning. Never an updated_at-style field.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Tremendous IDs are unique within an organization, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # False for tables that start disabled in the schema picker and one-shot setup.
    should_sync_default: bool = True


# Tremendous API v2 list endpoints (https://developers.tremendous.com). Paginated lists are ordered
# by creation date DESC and offset/limit paginated. Only /orders and /balance_transactions expose a
# server-side timestamp filter (`created_at[gte]`, ISO 8601), so they are the only incremental
# endpoints; nothing exposes an updated_at cursor, so every other endpoint is full refresh (see the
# implementing-warehouse-sources skill). /balance_transactions rows carry no id, so one is
# synthesized from the row's stable fields (see tremendous.py).
TREMENDOUS_ENDPOINTS: dict[str, TremendousEndpointConfig] = {
    "orders": TremendousEndpointConfig(
        path="/orders",
        data_key="orders",
        paginated=True,
        page_size=500,  # /orders caps `limit` at 500
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "rewards": TremendousEndpointConfig(
        path="/rewards",
        data_key="rewards",
        paginated=True,
        page_size=500,  # /rewards caps `limit` at 500
        partition_key="created_at",
    ),
    "invoices": TremendousEndpointConfig(
        path="/invoices",
        data_key="invoices",
        paginated=True,
        page_size=10,  # /invoices caps `limit` at 10
        partition_key="created_at",
    ),
    "members": TremendousEndpointConfig(path="/members", data_key="members"),
    "campaigns": TremendousEndpointConfig(path="/campaigns", data_key="campaigns"),
    "products": TremendousEndpointConfig(path="/products", data_key="products"),
    "funding_sources": TremendousEndpointConfig(path="/funding_sources", data_key="funding_sources"),
    # The account ledger: every debit/credit including fees, refunds, and balance adjustments.
    "balance_transactions": TremendousEndpointConfig(
        path="/balance_transactions",
        # Response wraps rows under "transactions", not the endpoint name.
        data_key="transactions",
        paginated=True,
        # The docs state only the default `limit` of 10 and no maximum. A limit above an
        # undocumented server cap would make every page look short and end pagination early,
        # silently truncating the table — so stay at the documented default.
        page_size=10,
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        # Rows have no API id; the synthesized primary key (see tremendous.py) is designed from
        # the API docs but unconfirmed against live accounts, so the table starts opt-in.
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(TREMENDOUS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TREMENDOUS_ENDPOINTS.items() if config.incremental_fields
}

SHOULD_SYNC_DEFAULT: dict[str, bool] = {
    name: config.should_sync_default for name, config in TREMENDOUS_ENDPOINTS.items()
}
