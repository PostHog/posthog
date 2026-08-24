from __future__ import annotations

from uuid import UUID

from products.managed_warehouse.backend import source_job_state
from products.managed_warehouse.backend.facade import api
from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehousePublishedTableRecord,
    ManagedWarehousePublishedTableStatus,
    ManagedWarehouseSourceJobUpdate,
)

__all__ = ["create_managed_warehouse_published_table_for_test", "record_source_job_state"]


def create_managed_warehouse_published_table_for_test(
    *,
    team_id: int,
    source_schema_name: str,
    source_table_name: str,
    name: str,
    status: ManagedWarehousePublishedTableStatus = ManagedWarehousePublishedTableStatus.PENDING,
    table_id: UUID | None = None,
    folder_version: str | None = None,
    deleted: bool = False,
) -> ManagedWarehousePublishedTableRecord:
    from products.data_modeling.backend.facade import api as data_modeling  # noqa: PLC0415
    from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery  # noqa: PLC0415
    from products.managed_warehouse.backend.models import ManagedWarehousePublishedTable  # noqa: PLC0415

    saved_query = data_modeling.create_managed_warehouse_saved_query(
        team_id=team_id,
        name=name,
        source_schema_name=source_schema_name,
        source_table_name=source_table_name,
    )
    saved_query_model = DataWarehouseSavedQuery.objects.get(team_id=team_id, id=saved_query.id)
    saved_query_model.status = {
        ManagedWarehousePublishedTableStatus.PENDING: DataWarehouseSavedQuery.Status.MODIFIED,
        ManagedWarehousePublishedTableStatus.PUBLISHING: DataWarehouseSavedQuery.Status.RUNNING,
        ManagedWarehousePublishedTableStatus.COMPLETED: DataWarehouseSavedQuery.Status.COMPLETED,
        ManagedWarehousePublishedTableStatus.FAILED: DataWarehouseSavedQuery.Status.FAILED,
    }[status]
    saved_query_model.table_id = table_id
    saved_query_model.save(update_fields=["status", "table", "updated_at"])
    ManagedWarehousePublishedTable.objects.for_team(team_id).create(
        team_id=team_id,
        saved_query_id=saved_query.id,
        source_schema_name=source_schema_name,
        source_table_name=source_table_name,
        name=name,
        status=status.value,
        table_id=table_id,
        folder_version=folder_version,
        deleted=deleted,
    )
    record = api.get_managed_warehouse_published_table(team_id, saved_query.id)
    assert record is not None
    return record


def record_source_job_state(input: ManagedWarehouseSourceJobUpdate) -> None:
    source_job_state.record_source_job_state(input)
