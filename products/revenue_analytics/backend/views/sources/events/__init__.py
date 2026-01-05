from posthog.schema import DatabaseSchemaManagedViewTableKind

from products.revenue_analytics.backend.views.core import Builder

from .charge import build as charge_builder
from .customer import build as customer_builder
from .mrr import build as mrr_builder
from .product import build as product_builder
from .revenue_item import build as revenue_item_builder
from .subscription import build as subscription_builder

BUILDER: Builder = {
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CHARGE: charge_builder,
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_SUBSCRIPTION: subscription_builder,
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CUSTOMER: customer_builder,
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_PRODUCT: product_builder,
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM: revenue_item_builder,
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_MRR: mrr_builder,  # Must be last, depends on revenue item and subscription to exist when building
}
