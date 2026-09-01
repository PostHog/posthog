from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from posthog.dataclasses import frozen

from products.managed_warehouse.backend.common import (
    duckgres_data_imports_schema,
    duckgres_data_imports_table_name,
    duckgres_data_modeling_schema,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceAccessMethod

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from products.managed_warehouse.backend.facade.contracts import ManagedWarehouseTableNames


@frozen
class _DuckLakeTableBinding:
    logical_name: str
    schema_name: str
    table_name: str


def bind_tables_to_ducklake(
    database: Any,
    team_id: int,
    *,
    data_imports_schema_name: str | None = None,
) -> tuple[_DuckLakeTableBinding, ...]:
    """Bind a built HogQL database's tables to their duckgres-materialized counterparts.

    On the warehouse HogQL database, both materialized data-modeling models and
    imported source tables resolve to the ClickHouse S3 table function (``s3(...)``),
    which DuckDB/duckgres cannot execute. The duckgres materialization / copy
    workflows write these into DuckLake schemas, so rebind each table node to a
    ``DirectPostgresTable`` that prints as the schema-qualified DuckLake name.

    Mutates ``database`` in place and returns the physical bindings it applied.
    Scoped to managed-warehouse compile paths only, so ClickHouse resolution is unchanged.
    """
    return (
        *_bind_materialized_models(database, team_id),
        *_bind_source_tables(database, team_id, schema_name=data_imports_schema_name),
    )


def build_trino_table_locators(
    database: Any,
    team_id: int,
    *,
    catalog_name: str,
    table_names: ManagedWarehouseTableNames,
) -> dict[str, tuple[str, str, str]]:
    """Build explicit Trino targets from the relations managed warehouse provisions."""
    locators = {
        "events": (catalog_name, "posthog", table_names.events_table),
        "persons": (catalog_name, "posthog", table_names.persons_table),
    }
    for binding in bind_tables_to_ducklake(
        database,
        team_id,
        data_imports_schema_name=table_names.data_imports_schema,
    ):
        locators[binding.logical_name] = (catalog_name, binding.schema_name, binding.table_name)
    return locators


def _bind_materialized_models(database: Any, team_id: int) -> list[_DuckLakeTableBinding]:
    """Bind materialized data-modeling models to their DuckLake schema (``shadow_<team_id>_models``)."""
    from posthog.hogql.database.direct_postgres_table import DirectPostgresTable
    from posthog.hogql.errors import ResolutionError

    from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

    schema_name = duckgres_data_modeling_schema(team_id)
    bindings: list[_DuckLakeTableBinding] = []
    materialized = DataWarehouseSavedQuery.objects.filter(
        team_id=team_id, is_materialized=True, table__isnull=False
    ).exclude(deleted=True)
    for saved_query in materialized:
        try:
            node = database.get_table_node(saved_query.name.split("."))
        except ResolutionError:
            logger.debug("Model %s not in HogQL database; skipping DuckLake bind", saved_query.name)
            continue
        existing = node.table
        if existing is None:
            continue
        node.table = DirectPostgresTable(
            name=saved_query.name,
            external_data_source_id="",
            postgres_schema=schema_name,
            postgres_table_name=saved_query.normalized_name,
            fields=existing.fields,
        )
        bindings.append(
            _DuckLakeTableBinding(
                logical_name=saved_query.name,
                schema_name=schema_name,
                table_name=saved_query.normalized_name,
            )
        )
    return bindings


def _bind_source_tables(
    database: Any,
    team_id: int,
    *,
    schema_name: str | None = None,
) -> list[_DuckLakeTableBinding]:
    """Bind imported source tables to their DuckLake-copied counterparts.

    Each queryable, S3-backed warehouse table that has a linked ``ExternalDataSchema`` was
    copied into the team's data-imports schema by the copy workflow. Model backing tables
    have no schema, so they are naturally skipped; direct-query tables already render
    schema-qualified and are not S3-backed, so they are skipped too. The binding is blind —
    if a table hasn't been synced yet, duckgres errors at query time, which is intended.
    """
    from posthog.hogql.database.direct_postgres_table import DirectPostgresTable
    from posthog.hogql.errors import ResolutionError

    from products.warehouse_sources.backend.facade.models import DataWarehouseTable

    schema_name = schema_name or duckgres_data_imports_schema(team_id)
    bindings: list[_DuckLakeTableBinding] = []
    tables = (
        DataWarehouseTable.objects.queryable()
        .filter(team_id=team_id, external_data_source__isnull=False)
        .exclude(external_data_source__access_method=ExternalDataSourceAccessMethod.DIRECT)
        .prefetch_related("externaldataschema_set__source")
    )
    for table in tables:
        external_schema = next(iter(table.externaldataschema_set.all()), None)
        if external_schema is None:
            continue
        try:
            node = database.get_table_node(table.name_chain)
        except ResolutionError:
            logger.debug("Source table %s not in HogQL database; skipping DuckLake bind", table.name)
            continue
        existing = node.table
        if existing is None:
            continue
        table_name = duckgres_data_imports_table_name(external_schema)
        node.table = DirectPostgresTable(
            name=table.name,
            external_data_source_id="",
            postgres_schema=schema_name,
            postgres_table_name=table_name,
            fields=existing.fields,
        )
        bindings.append(
            _DuckLakeTableBinding(
                logical_name=table.name,
                schema_name=schema_name,
                table_name=table_name,
            )
        )
    return bindings
