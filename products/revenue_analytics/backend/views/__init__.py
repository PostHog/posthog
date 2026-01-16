from typing import Literal

from posthog.hogql.database.models import SavedQuery

from products.data_warehouse.backend.types import DataWarehouseManagedViewSetKind

# Type alias for revenue analytics view kinds
RevenueAnalyticsViewKind = Literal[
    "revenue_analytics_charge",
    "revenue_analytics_customer",
    "revenue_analytics_mrr",
    "revenue_analytics_product",
    "revenue_analytics_revenue_item",
    "revenue_analytics_subscription",
]

# Alias constants for use in query building
CHARGE_ALIAS: RevenueAnalyticsViewKind = "revenue_analytics_charge"
CUSTOMER_ALIAS: RevenueAnalyticsViewKind = "revenue_analytics_customer"
MRR_ALIAS: RevenueAnalyticsViewKind = "revenue_analytics_mrr"
PRODUCT_ALIAS: RevenueAnalyticsViewKind = "revenue_analytics_product"
REVENUE_ITEM_ALIAS: RevenueAnalyticsViewKind = "revenue_analytics_revenue_item"
SUBSCRIPTION_ALIAS: RevenueAnalyticsViewKind = "revenue_analytics_subscription"


def is_revenue_analytics_view(saved_query: SavedQuery) -> bool:
    """Check if a SavedQuery is a revenue analytics managed view."""
    return saved_query.metadata.get("managed_viewset_kind") == DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS


def get_kind(saved_query: SavedQuery) -> RevenueAnalyticsViewKind | None:
    """Get the RevenueAnalyticsViewKind for a revenue analytics SavedQuery."""
    kind = saved_query.metadata.get("revenue_analytics_kind")
    if kind in (CHARGE_ALIAS, CUSTOMER_ALIAS, MRR_ALIAS, PRODUCT_ALIAS, REVENUE_ITEM_ALIAS, SUBSCRIPTION_ALIAS):
        return kind
    return None


def get_kind_alias(saved_query: SavedQuery) -> str:
    """Get the alias string for a revenue analytics SavedQuery (e.g., 'revenue_analytics_revenue_item')."""
    return saved_query.metadata.get("revenue_analytics_kind", "")


def is_event_view(saved_query: SavedQuery) -> bool:
    """Check if a SavedQuery is an event-based revenue analytics view."""
    return "revenue_analytics.events" in saved_query.name


def get_prefix(saved_query: SavedQuery) -> str:
    """Get the prefix from a revenue analytics SavedQuery name (e.g., 'stripe' from 'stripe.charge_revenue_view')."""
    return ".".join(saved_query.name.split(".")[:-1])
