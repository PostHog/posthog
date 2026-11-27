from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, IncrementalFieldType

SCHEMATIC_BASE_URL = "https://api.schematichq.com"

PAGE_SIZE = 100

# `/feature-usage-history` takes at most 250 rows a page and counts against the 2 requests a second
# analytics limit, so it reads the largest pages it can.
HISTORY_PAGE_SIZE = 250
# One request may span at most 366 daily buckets.
HISTORY_WINDOW = timedelta(days=365)
# The endpoint has no way to list from the first recorded usage, and Schematic launched in 2023.
HISTORY_START = datetime(2023, 1, 1, tzinfo=UTC)
# Late and backfilled events change recent daily buckets, so an incremental read starts a few days back.
HISTORY_LOOKBACK = timedelta(days=7)


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
    fanout: DependentEndpointConfig | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    page_size: int = PAGE_SIZE


_COMPANIES_ORDER = {"sort_order_column": "created_at", "sort_order_direction": "asc"}

# Feature usage rows carry no company, so each company is read on its own and keeps its id.
_FEATURE_USAGE_FANOUT = DependentEndpointConfig(
    parent_name="companies",
    resolve_param="company_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "company_id"},
    parent_params=_COMPANIES_ORDER,
)

FEATURE_USAGE_HISTORY = "feature_usage_history"


# Only `/feature-usage-history` takes a server-side time window, so every other table is full refresh.
# `/events` is left out on purpose: it has no time filter, and a full re-read of every usage event
# each sync is unbounded.
SCHEMATIC_ENDPOINTS: dict[str, SchematicEndpointConfig] = {
    # Companies change on every event, so pin a stable order for the offset walk and its resume.
    "companies": SchematicEndpointConfig(
        name="companies",
        path="/companies",
        extra_params=_COMPANIES_ORDER,
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
    "billing_credits": SchematicEndpointConfig(name="billing_credits", path="/billing/credits"),
    # An entitlement id repeats across companies, because a plan entitlement applies to every
    # company on the plan.
    "feature_usage": SchematicEndpointConfig(
        name="feature_usage",
        path="/feature-usage?company_id={company_id}",
        primary_keys=("company_id", "entitlement_id"),
        partition_key=None,
        fanout=_FEATURE_USAGE_FANOUT,
    ),
    # Daily usage per company, feature and event. Two features that measure one event each get a row.
    FEATURE_USAGE_HISTORY: SchematicEndpointConfig(
        name=FEATURE_USAGE_HISTORY,
        path="/feature-usage-history",
        primary_keys=("company_id", "feature_id", "event_subtype", "period_start"),
        partition_key="period_start",
        extra_params={"granularity": "daily"},
        incremental_fields=[
            IncrementalField(
                label="period_start",
                type=IncrementalFieldType.DateTime,
                field="period_start",
                field_type=IncrementalFieldType.DateTime,
            )
        ],
        default_incremental_field="period_start",
        page_size=HISTORY_PAGE_SIZE,
    ),
}

ENDPOINTS = tuple(SCHEMATIC_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SCHEMATIC_ENDPOINTS.items() if config.incremental_fields
}
