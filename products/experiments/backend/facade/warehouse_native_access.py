"""The connection access check that the query status endpoint runs for a warehouse-native experiment result."""

from typing import Any

from products.experiments.backend.warehouse_native_sources import (
    validate_warehouse_native_connection_access,
    warehouse_native_exposure_config,
)

# Stable wire identifier on an async query status. Renaming it needs a dual-read rollout and a drain of
# in-flight statuses, as for the managed warehouse labels.
WAREHOUSE_NATIVE_QUERY_STATUS_LABEL_PREFIX = "experiments-warehouse-native:"


def warehouse_native_connection_id(exposure_criteria: dict[str, Any] | None) -> str | None:
    """The connection a warehouse-native experiment reads, or None for an experiment that reads events."""
    exposure = warehouse_native_exposure_config(exposure_criteria)
    if exposure is None:
        return None
    return str(exposure.get("connection_id") or "")


__all__ = [
    "WAREHOUSE_NATIVE_QUERY_STATUS_LABEL_PREFIX",
    "validate_warehouse_native_connection_access",
    "warehouse_native_connection_id",
]
