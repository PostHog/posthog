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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.github.naming import (
    schema_repo_endpoint,
    split_schema_name as github_split_schema_name,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.constants import (
    CHARGE_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

github_schema_repo_endpoint = schema_repo_endpoint


def warehouse_parent_schema_names(source_type: str, schema_name: str) -> list[str]:
    """Sibling schemas `schema_name` reads from the warehouse instead of re-fetching.

    Non-empty only for fan-out children whose parent read comes from the parent schema's
    synced table (`DependentEndpointConfig.parent_source == "warehouse"`). The parents are
    not required to be enabled: the import activity checks usability per run and falls
    back to the parent API. An unknown or unregistered `source_type` returns `[]`, so
    callers outside the source tree (e.g. schedule building) never have to handle registry
    errors. The first call loads every source module; see `SourceRegistry._ensure_loaded`.
    """
    try:
        registered_type = ExternalDataSourceType(source_type)
    except ValueError:
        return []
    if not SourceRegistry.is_registered(registered_type):
        return []
    return SourceRegistry.get_source(registered_type).get_required_parent_schemas(schema_name)


__all__ = [
    "CHARGE_RESOURCE_NAME",
    "CUSTOMER_RESOURCE_NAME",
    "INVOICE_RESOURCE_NAME",
    "NamingConvention",
    "PRODUCT_RESOURCE_NAME",
    "SUBSCRIPTION_RESOURCE_NAME",
    "github_split_schema_name",
    "github_schema_repo_endpoint",
    "warehouse_parent_schema_names",
]
