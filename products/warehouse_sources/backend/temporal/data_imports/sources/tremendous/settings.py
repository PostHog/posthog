from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class TremendousEndpointConfig:
    name: str
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


# Tremendous API v2 list endpoints (https://developers.tremendous.com). Paginated lists are ordered
# by creation date DESC and offset/limit paginated. Only /orders exposes a server-side timestamp
# filter (`created_at[gte]`, ISO 8601), so it is the only incremental endpoint; nothing exposes an
# updated_at cursor, so every other endpoint is full refresh (see the implementing-warehouse-sources
# skill). /balance_transactions also filters on created_at but its rows carry no id, so it is
# deliberately excluded until a reliable composite key is confirmed.
TREMENDOUS_ENDPOINTS: dict[str, TremendousEndpointConfig] = {
    "orders": TremendousEndpointConfig(
        name="orders",
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
        name="rewards",
        path="/rewards",
        data_key="rewards",
        paginated=True,
        page_size=500,  # /rewards caps `limit` at 500
        partition_key="created_at",
    ),
    "invoices": TremendousEndpointConfig(
        name="invoices",
        path="/invoices",
        data_key="invoices",
        paginated=True,
        page_size=10,  # /invoices caps `limit` at 10
        partition_key="created_at",
    ),
    "members": TremendousEndpointConfig(name="members", path="/members", data_key="members"),
    "campaigns": TremendousEndpointConfig(name="campaigns", path="/campaigns", data_key="campaigns"),
    "products": TremendousEndpointConfig(name="products", path="/products", data_key="products"),
    "funding_sources": TremendousEndpointConfig(
        name="funding_sources", path="/funding_sources", data_key="funding_sources"
    ),
}

ENDPOINTS = tuple(TREMENDOUS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TREMENDOUS_ENDPOINTS.items() if config.incremental_fields
}
