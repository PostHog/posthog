from products.revenue_analytics.backend.views import (
    CHARGE_ALIAS,
    CUSTOMER_ALIAS,
    MRR_ALIAS,
    PRODUCT_ALIAS,
    REVENUE_ITEM_ALIAS,
    SUBSCRIPTION_ALIAS,
    RevenueAnalyticsViewKind,
)

from ._definitions import Schema
from .charge import SCHEMA as CHARGE
from .customer import SCHEMA as CUSTOMER
from .mrr import SCHEMA as MRR
from .product import SCHEMA as PRODUCT
from .revenue_item import SCHEMA as REVENUE_ITEM
from .subscription import SCHEMA as SUBSCRIPTION

SCHEMAS: dict[RevenueAnalyticsViewKind, Schema] = {
    SUBSCRIPTION_ALIAS: SUBSCRIPTION,
    REVENUE_ITEM_ALIAS: REVENUE_ITEM,
    CHARGE_ALIAS: CHARGE,
    CUSTOMER_ALIAS: CUSTOMER,
    PRODUCT_ALIAS: PRODUCT,
    MRR_ALIAS: MRR,
}
