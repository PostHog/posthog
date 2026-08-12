from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _timestamp_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


# Katana mutable resources expose both created_at and updated_at; updated_at is the default cursor
# so incremental syncs also pick up edits to existing rows.
_UPDATED_AND_CREATED: list[IncrementalField] = [_timestamp_field("updated_at"), _timestamp_field("created_at")]
# Append-only logs (inventory movements) are immutable, so created_at is the only stable cursor.
_CREATED_ONLY: list[IncrementalField] = [_timestamp_field("created_at")]


@dataclass
class KatanaEndpointConfig:
    name: str
    path: str
    # Katana ids are globally unique per resource, so a single-column key is enough for most tables.
    # Inventory has no id (it's a per-(variant, location) balance), so it uses a composite key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time column to partition on. Never updated_at — partitions must not move.
    partition_key: str | None = "created_at"
    default_incremental_field: str = "updated_at"


KATANA_ENDPOINTS: dict[str, KatanaEndpointConfig] = {
    # --- Catalog ---
    "products": KatanaEndpointConfig(name="products", path="/products", incremental_fields=_UPDATED_AND_CREATED),
    "materials": KatanaEndpointConfig(name="materials", path="/materials", incremental_fields=_UPDATED_AND_CREATED),
    "variants": KatanaEndpointConfig(name="variants", path="/variants", incremental_fields=_UPDATED_AND_CREATED),
    "services": KatanaEndpointConfig(name="services", path="/services", incremental_fields=_UPDATED_AND_CREATED),
    # --- Partners ---
    "customers": KatanaEndpointConfig(name="customers", path="/customers", incremental_fields=_UPDATED_AND_CREATED),
    "suppliers": KatanaEndpointConfig(name="suppliers", path="/suppliers", incremental_fields=_UPDATED_AND_CREATED),
    # --- Orders ---
    "sales_orders": KatanaEndpointConfig(
        name="sales_orders", path="/sales_orders", incremental_fields=_UPDATED_AND_CREATED
    ),
    "purchase_orders": KatanaEndpointConfig(
        name="purchase_orders", path="/purchase_orders", incremental_fields=_UPDATED_AND_CREATED
    ),
    "manufacturing_orders": KatanaEndpointConfig(
        name="manufacturing_orders", path="/manufacturing_orders", incremental_fields=_UPDATED_AND_CREATED
    ),
    "sales_returns": KatanaEndpointConfig(
        name="sales_returns", path="/sales_returns", incremental_fields=_UPDATED_AND_CREATED
    ),
    # --- Stock movements ---
    "stock_adjustments": KatanaEndpointConfig(
        name="stock_adjustments", path="/stock_adjustments", incremental_fields=_UPDATED_AND_CREATED
    ),
    "stock_transfers": KatanaEndpointConfig(
        name="stock_transfers", path="/stock_transfers", incremental_fields=_UPDATED_AND_CREATED
    ),
    "stocktakes": KatanaEndpointConfig(name="stocktakes", path="/stocktakes", incremental_fields=_UPDATED_AND_CREATED),
    "inventory_movements": KatanaEndpointConfig(
        name="inventory_movements",
        path="/inventory_movements",
        incremental_fields=_CREATED_ONLY,
        default_incremental_field="created_at",
    ),
    # --- Full refresh only ---
    # /inventory has no created_at/updated_at filter (it's a live per-(variant, location) balance),
    # so there is no server-side cursor to sync incrementally.
    "inventory": KatanaEndpointConfig(
        name="inventory",
        path="/inventory",
        primary_keys=["variant_id", "location_id"],
        incremental_fields=[],
        partition_key=None,
    ),
    # /price_lists exposes no timestamp filter, and these config tables are small, so full refresh.
    "price_lists": KatanaEndpointConfig(
        name="price_lists", path="/price_lists", incremental_fields=[], partition_key=None
    ),
    "locations": KatanaEndpointConfig(name="locations", path="/locations", incremental_fields=[], partition_key=None),
    "tax_rates": KatanaEndpointConfig(name="tax_rates", path="/tax_rates", incremental_fields=[], partition_key=None),
}

ENDPOINTS = tuple(KATANA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in KATANA_ENDPOINTS.items()
}
