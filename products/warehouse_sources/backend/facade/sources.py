"""
Source-domain wiring for warehouse_sources.

Light, framework-free constants and naming helpers that live under the source tree
and are referenced by sibling products (revenue_analytics' stripe views, the
data-modeling saved-query naming). Heavier source-connection internals (HogQL
direct-SQL's mysql/postgres configs and drivers, the Google Search Console session
helpers) stay behind named legacy-leaks rather than being re-exported here, so the
facade import path doesn't drag in DB drivers or the Google client libraries.
"""

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.constants import (
    CHARGE_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
)

__all__ = [
    "CHARGE_RESOURCE_NAME",
    "CUSTOMER_RESOURCE_NAME",
    "INVOICE_RESOURCE_NAME",
    "NamingConvention",
    "PRODUCT_RESOURCE_NAME",
    "SUBSCRIPTION_RESOURCE_NAME",
]
