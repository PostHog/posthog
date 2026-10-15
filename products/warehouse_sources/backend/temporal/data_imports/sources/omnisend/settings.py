from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField

OMNISEND_V3 = "v3"
# Header-versioned (`Omnisend-Version`) on the `/api` base path, with `Authorization: Omnisend-API-Key`.
OMNISEND_2026_03_15 = "2026-03-15"


@dataclass(frozen=True)
class OmnisendWire:
    path: str
    data_key: str  # Response array key, e.g. {"contacts": [...], "paging": {...}}
    primary_key: str
    # Opaque `paging.cursors.after` tokens instead of a fully-formed `paging.next` URL.
    cursor_paginated: bool = False


@dataclass(frozen=True)
class OmnisendEndpointConfig:
    name: str
    # Request shape per supported API version. A version missing here has no list endpoint for
    # the resource, so the table is not offered on that version.
    wires: dict[str, OmnisendWire]
    # Stable creation-time field used for delta partitioning. Never a mutable field
    # like updatedAt — partitions would rewrite on every sync.
    partition_key: Optional[str] = None
    # Advertised incremental options. Empty = full refresh only (see api_inventory.md:
    # Omnisend's only server-side timestamp filter is unverified, so we ship full refresh).
    incremental_fields: list[IncrementalField] = field(default_factory=list)


OMNISEND_ENDPOINTS: dict[str, OmnisendEndpointConfig] = {
    "contacts": OmnisendEndpointConfig(
        name="contacts",
        wires={
            OMNISEND_V3: OmnisendWire(path="/contacts", data_key="contacts", primary_key="contactID"),
            OMNISEND_2026_03_15: OmnisendWire(
                path="/contacts", data_key="contacts", primary_key="id", cursor_paginated=True
            ),
        },
        partition_key="createdAt",
    ),
    "campaigns": OmnisendEndpointConfig(
        name="campaigns",
        wires={
            # `/v3/campaigns` is the one v3 list endpoint that nests its rows under the singular
            # `campaign` key; every other resource uses the plural `<resource>` convention.
            OMNISEND_V3: OmnisendWire(path="/campaigns", data_key="campaign", primary_key="campaignID"),
            OMNISEND_2026_03_15: OmnisendWire(
                path="/campaigns", data_key="campaigns", primary_key="id", cursor_paginated=True
            ),
        },
        partition_key="createdAt",
    ),
    "carts": OmnisendEndpointConfig(
        name="carts",
        wires={OMNISEND_V3: OmnisendWire(path="/carts", data_key="carts", primary_key="cartID")},
        partition_key="createdAt",
    ),
    "orders": OmnisendEndpointConfig(
        name="orders",
        wires={OMNISEND_V3: OmnisendWire(path="/orders", data_key="orders", primary_key="orderID")},
        partition_key="createdAt",
    ),
    "products": OmnisendEndpointConfig(
        name="products",
        wires={
            OMNISEND_V3: OmnisendWire(path="/products", data_key="products", primary_key="productID"),
            OMNISEND_2026_03_15: OmnisendWire(path="/products", data_key="products", primary_key="id"),
        },
        partition_key="createdAt",
    ),
    "categories": OmnisendEndpointConfig(
        name="categories",
        wires={
            OMNISEND_V3: OmnisendWire(path="/categories", data_key="categories", primary_key="categoryID"),
            OMNISEND_2026_03_15: OmnisendWire(
                path="/product-categories", data_key="categories", primary_key="categoryID"
            ),
        },
    ),
}

ENDPOINTS = tuple(OMNISEND_ENDPOINTS.keys())


def endpoints_for_version(api_version: str) -> tuple[str, ...]:
    return tuple(name for name, config in OMNISEND_ENDPOINTS.items() if api_version in config.wires)


INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in OMNISEND_ENDPOINTS.items()
}
