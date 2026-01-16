from products.revenue_analytics.backend.views import (
    CHARGE_ALIAS,
    CUSTOMER_ALIAS,
    MRR_ALIAS,
    PRODUCT_ALIAS,
    REVENUE_ITEM_ALIAS,
    SUBSCRIPTION_ALIAS,
)
from products.revenue_analytics.backend.views.core import Builder

from .charge import build as charge_builder
from .customer import build as customer_builder
from .mrr import build as mrr_builder
from .product import build as product_builder
from .revenue_item import build as revenue_item_builder
from .subscription import build as subscription_builder

BUILDER: Builder = {
    CHARGE_ALIAS: charge_builder,
    CUSTOMER_ALIAS: customer_builder,
    PRODUCT_ALIAS: product_builder,
    REVENUE_ITEM_ALIAS: revenue_item_builder,
    SUBSCRIPTION_ALIAS: subscription_builder,
    MRR_ALIAS: mrr_builder,  # Must be last, depends on revenue item and subscription to exist when building
}
