"""The connection access check that the query status endpoint runs for a warehouse-native experiment result."""

from products.experiments.backend.warehouse_native_sources import validate_warehouse_native_connection_access

# Stable wire identifier on an async query status. Renaming it needs a dual-read rollout and a drain of
# in-flight statuses, as for the managed warehouse labels.
WAREHOUSE_NATIVE_QUERY_STATUS_LABEL_PREFIX = "experiments-warehouse-native:"

__all__ = [
    "WAREHOUSE_NATIVE_QUERY_STATUS_LABEL_PREFIX",
    "validate_warehouse_native_connection_access",
]
