from dataclasses import dataclass

from products.warehouse_sources.backend.types import IncrementalField

SCHEMATIC_BASE_URL = "https://api.schematichq.com"

PAGE_SIZE = 100


@dataclass(frozen=True)
class SchematicEndpointConfig:
    name: str
    path: str
    primary_keys: tuple[str, ...] = ("id",)
    # Billing customers, coupons and meters have no creation timestamp, so they stay unpartitioned.
    partition_key: str | None = "created_at"


# No list endpoint takes a server-side `updated_after` style filter, so every table is full refresh.
# `/events` is left out on purpose: it has no time filter either, and a full re-read of every usage
# event each sync is unbounded.
SCHEMATIC_ENDPOINTS: dict[str, SchematicEndpointConfig] = {
    "companies": SchematicEndpointConfig(name="companies", path="/companies"),
    "users": SchematicEndpointConfig(name="users", path="/users"),
    "company_memberships": SchematicEndpointConfig(name="company_memberships", path="/company-memberships"),
    "features": SchematicEndpointConfig(name="features", path="/features"),
    "flags": SchematicEndpointConfig(name="flags", path="/flags"),
    "plans": SchematicEndpointConfig(name="plans", path="/plans"),
    "plan_entitlements": SchematicEndpointConfig(name="plan_entitlements", path="/plan-entitlements"),
    "company_overrides": SchematicEndpointConfig(name="company_overrides", path="/company-overrides"),
    "billing_customers": SchematicEndpointConfig(
        name="billing_customers", path="/billing/customers", partition_key=None
    ),
    "billing_products": SchematicEndpointConfig(
        name="billing_products", path="/billing/products", primary_keys=("product_id",)
    ),
    "billing_prices": SchematicEndpointConfig(name="billing_prices", path="/billing/price"),
    "billing_coupons": SchematicEndpointConfig(name="billing_coupons", path="/billing/coupons", partition_key=None),
    "billing_meters": SchematicEndpointConfig(name="billing_meters", path="/billing/meter", partition_key=None),
}

ENDPOINTS = tuple(SCHEMATIC_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
