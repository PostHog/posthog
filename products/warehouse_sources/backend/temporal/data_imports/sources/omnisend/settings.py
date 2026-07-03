from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class OmnisendEndpointConfig:
    name: str
    path: str
    data_key: str  # Response array key, e.g. {"contacts": [...], "paging": {...}}
    primary_key: str
    # Stable creation-time field used for delta partitioning. Never a mutable field
    # like updatedAt — partitions would rewrite on every sync.
    partition_key: Optional[str] = None
    # Advertised incremental options. Empty = full refresh only (see api_inventory.md:
    # Omnisend's only server-side timestamp filter is unverified, so we ship full refresh).
    incremental_fields: list[IncrementalField] = field(default_factory=list)


OMNISEND_ENDPOINTS: dict[str, OmnisendEndpointConfig] = {
    "contacts": OmnisendEndpointConfig(
        name="contacts",
        path="/contacts",
        data_key="contacts",
        primary_key="contactID",
        partition_key="createdAt",
    ),
    "campaigns": OmnisendEndpointConfig(
        name="campaigns",
        path="/campaigns",
        data_key="campaigns",
        primary_key="campaignID",
        partition_key="createdAt",
    ),
    "carts": OmnisendEndpointConfig(
        name="carts",
        path="/carts",
        data_key="carts",
        primary_key="cartID",
        partition_key="createdAt",
    ),
    "orders": OmnisendEndpointConfig(
        name="orders",
        path="/orders",
        data_key="orders",
        primary_key="orderID",
        partition_key="createdAt",
    ),
    "products": OmnisendEndpointConfig(
        name="products",
        path="/products",
        data_key="products",
        primary_key="productID",
        partition_key="createdAt",
    ),
    "categories": OmnisendEndpointConfig(
        name="categories",
        path="/categories",
        data_key="categories",
        primary_key="categoryID",
    ),
}

ENDPOINTS = tuple(OMNISEND_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in OMNISEND_ENDPOINTS.items()
}
