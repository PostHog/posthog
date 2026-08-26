from __future__ import annotations

from uuid import UUID

from products.managed_warehouse.backend import source_job_state
from products.managed_warehouse.backend.facade.contracts import ManagedWarehouseSourceJobRecord

__all__ = ["list_latest_source_jobs"]


def list_latest_source_jobs(*, team_id: int, schema_ids: list[UUID]) -> list[ManagedWarehouseSourceJobRecord]:
    return source_job_state.list_latest_source_jobs(team_id=team_id, schema_ids=schema_ids)
