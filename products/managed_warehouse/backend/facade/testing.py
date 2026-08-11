from __future__ import annotations

from products.managed_warehouse.backend import source_job_state
from products.managed_warehouse.backend.facade.contracts import ManagedWarehouseSourceJobUpdate

__all__ = ["record_source_job_state"]


def record_source_job_state(input: ManagedWarehouseSourceJobUpdate) -> None:
    source_job_state.record_source_job_state(input)
