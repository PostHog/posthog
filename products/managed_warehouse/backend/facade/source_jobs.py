from __future__ import annotations

from datetime import datetime, tzinfo
from uuid import UUID

from products.managed_warehouse.backend import source_job_state
from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseSourceJobDayCount,
    ManagedWarehouseSourceJobRecord,
)

__all__ = ["count_finished_source_jobs_by_day", "list_latest_source_jobs"]


def list_latest_source_jobs(*, team_id: int, schema_ids: list[UUID]) -> list[ManagedWarehouseSourceJobRecord]:
    return source_job_state.list_latest_source_jobs(team_id=team_id, schema_ids=schema_ids)


def count_finished_source_jobs_by_day(
    *, team_id: int, schema_ids: list[UUID], start: datetime, end: datetime, tz: tzinfo
) -> list[ManagedWarehouseSourceJobDayCount]:
    return source_job_state.count_finished_source_jobs_by_day(
        team_id=team_id, schema_ids=schema_ids, start=start, end=end, tz=tz
    )
