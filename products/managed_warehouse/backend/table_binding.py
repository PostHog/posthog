from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from posthog.hogql.database.trino_locator import TrinoTableLocator

from products.managed_warehouse.backend.common import (
    duckgres_data_imports_schema,
    duckgres_data_imports_table_name,
    duckgres_data_modeling_schema,
    ducklake_data_modeling_schema,
    ducklake_data_modeling_table_name,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceAccessMethod

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from products.managed_warehouse.backend.facade.contracts import ManagedWarehouseTableNames


def bind_tables_to_ducklake(database: Any, team_id: int) -> None:
    """Bind a built HogQL database's tables to their duckgres-materialized counterparts.

    On the warehouse HogQL database, both materialized data-modeling models and
    imported source tables resolve to the ClickHouse S3 table function (``s3(...)``),
    which DuckDB/duckgres cannot execute. The duckgres materialization / copy
    workflows write these into DuckLake schemas, so rebind each table node to a
    ``DirectPostgresTable`` that prints as the schema-qualified DuckLake name.

    Mutates ``database`` in place. Scoped to the DuckLake compile path only — the
    ClickHouse path never calls this, so its table resolution is unchanged.
    """
    _bind_materialized_models(database, team_id)
    _bind_source_tables(database, team_id)


def build_trino_table_locators(
    database: Any,
    team_id: int,
    *,
    catalog_name: str,
    table_names: ManagedWarehouseTableNames,
) -> dict[str, TrinoTableLocator]:
    """Build explicit Trino targets from the relations managed warehouse provisions."""
    from products.data_modeling.backend.facade.modeling import DataWarehouseModelPath
    from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
    from products.managed_warehouse.backend.facade import team_state as team_state_facade
    from products.warehouse_sources.backend.facade.ducklake import list_ducklake_imported_tables

    locators: dict[str, TrinoTableLocator] = {
        "events": (catalog_name, "posthog", table_names.events_table),
        "persons": (catalog_name, "posthog", table_names.persons_table),
    }

    model_schema = ducklake_data_modeling_schema(team_id)
    materialized_models = list(
        DataWarehouseSavedQuery.objects.filter(team_id=team_id, is_materialized=True, table__isnull=False).exclude(
            deleted=True
        )
    )
    model_labels_by_saved_query_id = {
        saved_query_id: path[-1]
        for saved_query_id, path in DataWarehouseModelPath.objects.filter(
            team_id=team_id,
            saved_query_id__in=[saved_query.id for saved_query in materialized_models],
        ).values_list("saved_query_id", "path")
        if path
    }
    for saved_query in materialized_models:
        if database.has_table(saved_query.name):
            model_label = model_labels_by_saved_query_id.get(saved_query.id, saved_query.id.hex)
            locators[saved_query.name] = (
                catalog_name,
                model_schema,
                ducklake_data_modeling_table_name(model_label, saved_query.normalized_name),
            )

    naming_version = team_state_facade.data_imports_table_naming_version(team_id)
    for table in list_ducklake_imported_tables(team_id, naming_version):
        locator = (catalog_name, table_names.data_imports_schema, table.physical_table_name)
        for logical_name in table.logical_table_names:
            if database.has_table(logical_name):
                locators[logical_name] = locator

    return locators


def _bind_materialized_models(database: Any, team_id: int) -> None:
    """Bind materialized data-modeling models to their DuckLake schema (``shadow_<team_id>_models``)."""
    from posthog.hogql.database.direct_postgres_table import DirectPostgresTable
    from posthog.hogql.errors import ResolutionError

    from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

    schema_name = duckgres_data_modeling_schema(team_id)
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


def _bind_source_tables(database: Any, team_id: int) -> None:
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

    schema_name = duckgres_data_imports_schema(team_id)
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
        node.table = DirectPostgresTable(
            name=table.name,
            external_data_source_id="",
            postgres_schema=schema_name,
            postgres_table_name=duckgres_data_imports_table_name(external_schema),
            fields=existing.fields,
        )
