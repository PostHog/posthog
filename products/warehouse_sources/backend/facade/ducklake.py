from __future__ import annotations

from posthog.hogql.database.database import get_data_warehouse_table_name

from products.warehouse_sources.backend.duckgres_naming import duckgres_data_imports_table_name_for_version
from products.warehouse_sources.backend.models.table import DataWarehouseTable

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
