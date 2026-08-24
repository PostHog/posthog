from collections.abc import Mapping
from uuid import UUID

from django.db import transaction

from products.warehouse_sources.backend.models.table import DataWarehouseTable


def active_table_name_exists(*, team_id: int, name: str) -> bool:
    return DataWarehouseTable.objects.filter(team_id=team_id, name=name).exclude(deleted=True).exists()


def prepare_table_registration(
    *, team_id: int, table_id: UUID | None, name: str, url_pattern: str
) -> DataWarehouseTable:
    table = None
    if table_id is not None:
        table = DataWarehouseTable.objects.filter(team_id=team_id, id=table_id).first()
    if table is None:
        table = DataWarehouseTable(
            team_id=team_id,
            name=name,
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern=url_pattern,
            created_via=DataWarehouseTable.CreatedVia.MATERIALIZED_VIEW,
        )
    else:
        table.format = DataWarehouseTable.TableFormat.Parquet
        table.url_pattern = url_pattern
        table.created_via = DataWarehouseTable.CreatedVia.MATERIALIZED_VIEW

    table.set_columns(table.get_columns())
    return table


@transaction.atomic
def save_table_registration(
    *,
    table_id: UUID,
    team_id: int,
    name: str,
    url_pattern: str,
    columns: Mapping[str, object],
    row_count: int,
    size_in_s3_mib: float,
) -> DataWarehouseTable:
    table = DataWarehouseTable.objects.filter(team_id=team_id, id=table_id).first()
    if table is None:
        table = DataWarehouseTable(
            id=table_id,
            team_id=team_id,
            name=name,
            format=DataWarehouseTable.TableFormat.Parquet,
            url_pattern=url_pattern,
            created_via=DataWarehouseTable.CreatedVia.MATERIALIZED_VIEW,
        )
    else:
        table.format = DataWarehouseTable.TableFormat.Parquet
        table.url_pattern = url_pattern
        table.created_via = DataWarehouseTable.CreatedVia.MATERIALIZED_VIEW

    table.save(internally_computed_url_pattern=True)
    table.set_columns(dict(columns))
    table.row_count = row_count
    table.size_in_s3_mib = size_in_s3_mib
    table.save()
    return table


@transaction.atomic
def soft_delete_table_if_exists(*, team_id: int, table_id: UUID) -> bool:
    table = DataWarehouseTable.objects.filter(team_id=team_id, id=table_id).first()
    if table is None:
        return False
    table.soft_delete()
    return True
