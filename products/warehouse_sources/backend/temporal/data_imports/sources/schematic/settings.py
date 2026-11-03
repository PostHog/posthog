from dataclasses import dataclass, field

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
    # Read once with `is_active=true` and once with `is_active=false`. Products and prices list only
    # active records by default, and the coupons default is undocumented.
    include_inactive: bool = False
    extra_params: dict[str, str] = field(default_factory=dict)


# No list endpoint takes a server-side `updated_after` style filter, so every table is full refresh.
# `/events` is left out on purpose: it has no time filter either, and a full re-read of every usage
# event each sync is unbounded.
SCHEMATIC_ENDPOINTS: dict[str, SchematicEndpointConfig] = {
    # Companies change on every event, so pin a stable order for the offset walk and its resume.
    "companies": SchematicEndpointConfig(
        name="companies",
        path="/companies",
        extra_params={"sort_order_column": "created_at", "sort_order_direction": "asc"},
    ),
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
        name="billing_products", path="/billing/products", primary_keys=("product_id",), include_inactive=True
    ),
    "billing_prices": SchematicEndpointConfig(name="billing_prices", path="/billing/price", include_inactive=True),
    "billing_coupons": SchematicEndpointConfig(
        name="billing_coupons", path="/billing/coupons", partition_key=None, include_inactive=True
    ),
    "billing_meters": SchematicEndpointConfig(name="billing_meters", path="/billing/meter", partition_key=None),
}

ENDPOINTS = tuple(SCHEMATIC_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
