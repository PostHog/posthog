"""The view-kind builder registry for the Checkout.com source (see the package docstring)."""

from posthog.schema import DatabaseSchemaManagedViewTableKind

from products.revenue_analytics.backend.views.core import Builder

from .charge import build as charge_builder
from .customer import build as customer_builder
from .revenue_item import build as revenue_item_builder

BUILDER: Builder = {
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CHARGE: charge_builder,
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CUSTOMER: customer_builder,
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM: revenue_item_builder,
}
