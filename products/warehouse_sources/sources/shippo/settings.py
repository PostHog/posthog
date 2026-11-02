from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class ShippoEndpointConfig:
    name: str
    path: str
    # Shippo object_ids are unique per account across each resource type.
    primary_keys: list[str] = field(default_factory=lambda: ["object_id"])
    # Stable creation-time field used for datetime partitioning. Never an updated_at-style
    # field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    # Only /shipments accepts the server-side object_created_gt/gte/lt/lte filters (per Shippo's
    # filtering docs); every other list endpoint is page/results pagination only.
    supports_created_filter: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)


# Shippo list endpoints all return {"next": url|null, "previous": url|null, "results": [...]}
# and paginate with `page` + `results` (max 100). Only shipments supports server-side
# creation-date filtering, so it is the only endpoint advertised as incremental; orders expose
# `start_date`/`end_date` but those filter on `placed_at` (when the order was placed in the shop,
# not when the object was created in Shippo) and order status is mutable, so orders stay full
# refresh to avoid missing late-imported or updated rows.
SHIPPO_ENDPOINTS: dict[str, ShippoEndpointConfig] = {
    "shipments": ShippoEndpointConfig(
        name="shipments",
        path="/shipments",
        partition_key="object_created",
        supports_created_filter=True,
        incremental_fields=[
            {
                "label": "object_created",
                "type": IncrementalFieldType.DateTime,
                "field": "object_created",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "transactions": ShippoEndpointConfig(
        name="transactions",
        path="/transactions",
        partition_key="object_created",
    ),
    "orders": ShippoEndpointConfig(
        name="orders",
        path="/orders",
        # Orders have no object_created field; placed_at is required and stable once set.
        partition_key="placed_at",
    ),
    "addresses": ShippoEndpointConfig(
        name="addresses",
        path="/addresses",
        partition_key="object_created",
    ),
    "parcels": ShippoEndpointConfig(
        name="parcels",
        path="/parcels",
        partition_key="object_created",
    ),
    "carrier_accounts": ShippoEndpointConfig(
        name="carrier_accounts",
        path="/carrier_accounts",
        # Carrier account objects carry no object_created, and the table is tiny — no partitioning.
    ),
    "refunds": ShippoEndpointConfig(
        name="refunds",
        path="/refunds",
        partition_key="object_created",
    ),
    "customs_items": ShippoEndpointConfig(
        name="customs_items",
        path="/customs/items",
        partition_key="object_created",
    ),
    "customs_declarations": ShippoEndpointConfig(
        name="customs_declarations",
        path="/customs/declarations",
        partition_key="object_created",
    ),
}

ENDPOINTS = tuple(SHIPPO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SHIPPO_ENDPOINTS.items() if config.incremental_fields
}
