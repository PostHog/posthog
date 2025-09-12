from posthog.schema import DatabaseSchemaManagedViewTableKind

from ._definitions import Schema
from .charge import SCHEMA as CHARGE
from .customer import SCHEMA as CUSTOMER
from .product import SCHEMA as PRODUCT
from .revenue_item import SCHEMA as REVENUE_ITEM
from .subscription import SCHEMA as SUBSCRIPTION

SCHEMAS: dict[DatabaseSchemaManagedViewTableKind, Schema] = {
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_SUBSCRIPTION: SUBSCRIPTION,
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM: REVENUE_ITEM,
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CHARGE: CHARGE,
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CUSTOMER: CUSTOMER,
    DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_PRODUCT: PRODUCT,
}
