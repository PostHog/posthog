from __future__ import annotations

from products.managed_warehouse.backend import managed_ingress, source_job_state
from products.managed_warehouse.backend.facade.contracts import ManagedWarehouseSourceJobUpdate

__all__ = ["NO_MANAGED_WAREHOUSE_TARGET", "record_source_job_state"]

# The warehouse-source host guard's tests assert that a denial is recognised after the cache
# serializes it. They cannot reach the sentinel through `managed_ingress` without breaking the
# product's public-interface rule, so the facade re-exports it.
NO_MANAGED_WAREHOUSE_TARGET = managed_ingress._NO_TARGET


def record_source_job_state(input: ManagedWarehouseSourceJobUpdate) -> None:
    source_job_state.record_source_job_state(input)
