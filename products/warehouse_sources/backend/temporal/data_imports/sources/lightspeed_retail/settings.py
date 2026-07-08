from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Every X-Series v2.0 record carries a monotonically increasing integer
# `version`; the same `after=<version>` param used for keyset pagination doubles
# as a lossless incremental cursor, so the menu is shared across endpoints.
_VERSION_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "version",
        "type": IncrementalFieldType.Integer,
        "field": "version",
        "field_type": IncrementalFieldType.Integer,
    },
]


@dataclass
class LightspeedRetailEndpointConfig:
    name: str
    path: str
    primary_key: str = "id"
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: list(_VERSION_INCREMENTAL_FIELDS))
    # Stable creation-time field used for datetime partitioning. Never a
    # version/updated-style field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None


LIGHTSPEED_RETAIL_ENDPOINTS: dict[str, LightspeedRetailEndpointConfig] = {
    "sales": LightspeedRetailEndpointConfig(
        name="sales",
        path="/sales",
        partition_key="sale_date",
    ),
    "customers": LightspeedRetailEndpointConfig(
        name="customers",
        path="/customers",
        partition_key="created_at",
    ),
    "products": LightspeedRetailEndpointConfig(
        name="products",
        path="/products",
        partition_key="created_at",
    ),
    "inventory": LightspeedRetailEndpointConfig(
        name="inventory",
        path="/inventory",
    ),
    "outlets": LightspeedRetailEndpointConfig(
        name="outlets",
        path="/outlets",
    ),
    "registers": LightspeedRetailEndpointConfig(
        name="registers",
        path="/registers",
    ),
    "users": LightspeedRetailEndpointConfig(
        name="users",
        path="/users",
    ),
    "taxes": LightspeedRetailEndpointConfig(
        name="taxes",
        path="/taxes",
    ),
}

ENDPOINTS = tuple(LIGHTSPEED_RETAIL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LIGHTSPEED_RETAIL_ENDPOINTS.items() if config.incremental_fields
}
