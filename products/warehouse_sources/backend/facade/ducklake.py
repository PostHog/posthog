from __future__ import annotations

from typing import Any

from posthog.hogql.database.database import get_data_warehouse_table_name

from products.warehouse_sources.backend.duckgres_naming import duckgres_data_imports_table_name_for_version
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.query_folder_state import (
    QueryFolderPointerHistory,
    query_folder_table_prefix,
)

from .contracts import DuckLakeImportedTable
from .types import ExternalDataSourceAccessMethod


def list_ducklake_imported_tables(team_id: int, naming_version: str) -> list[DuckLakeImportedTable]:
    tables = (
        DataWarehouseTable.objects.queryable()
        .filter(team_id=team_id, external_data_source__isnull=False)
        .exclude(external_data_source__access_method=ExternalDataSourceAccessMethod.DIRECT)
        .prefetch_related("externaldataschema_set__source")
    )

    imported_tables: list[DuckLakeImportedTable] = []
    for table in tables:
        external_schema = next(iter(table.externaldataschema_set.all()), None)
        if external_schema is None:
            continue

        imported_tables.append(
            DuckLakeImportedTable(
                logical_table_names=tuple(
                    dict.fromkeys((table.name, get_data_warehouse_table_name(external_schema.source, table.name)))
                ),
                physical_table_name=duckgres_data_imports_table_name_for_version(
                    external_schema.source.source_type,
                    external_schema.source.prefix,
                    external_schema.normalized_name,
                    naming_version,
                ),
            )
        )

    return imported_tables


def query_folder_publishing_job_id(sync_type_config: Any, queryable_folder: str) -> str | None:
    """The import job that pointed the table at `queryable_folder`, or None when the pointer is
    elsewhere or the move was not recorded.

    A query folder with a fixed name is reused by later syncs, so the folder name alone does not
    identify a generation of the table; the job that published it does.
    """
    history = QueryFolderPointerHistory.from_config(sync_type_config, query_folder_table_prefix(queryable_folder))
    if history is None or history.active != queryable_folder:
        return None
    return history.active_job_id


def schema_sync_type_config(*, team_id: int, schema_id: Any) -> Any | None:
    """The schema's raw `sync_type_config`, or None when the schema no longer exists.

    A plain field read behind the facade, so a caller outside this product (e.g. the DuckLake
    registration workflow, which needs it to resolve `query_folder_publishing_job_id`) never has to
    reach for `ExternalDataSchema` directly.
    """
    return (
        ExternalDataSchema.objects.filter(id=schema_id, team_id=team_id)
        .values_list("sync_type_config", flat=True)
        .first()
    )
