from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any
from uuid import UUID

from posthog.hogql.database.direct_trino_table import is_managed_trino_external_catalog
from posthog.hogql.database.trino_locator import TrinoTableLocator

from products.managed_warehouse.backend.common import (
    duckgres_data_imports_schema,
    duckgres_data_imports_table_name,
    duckgres_data_modeling_schema,
    ducklake_data_modeling_schema,
    ducklake_data_modeling_table_name,
)
from products.managed_warehouse.backend.storage_location import delta_table_root
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


def get_data_modeling_table_names(team_id: int, saved_query_ids: Sequence[UUID]) -> dict[UUID, str]:
    return {
        saved_query_id: ducklake_data_modeling_table_name(saved_query_id.hex, saved_query_id.hex)
        for saved_query_id in saved_query_ids
    }


def build_trino_table_locators(
    database: Any,
    team_id: int,
    *,
    catalog_name: str,
    table_names: ManagedWarehouseTableNames,
) -> dict[str, TrinoTableLocator]:
    """Build explicit Trino targets from the relations managed warehouse provisions."""
    from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
    from products.managed_warehouse.backend.facade import team_state as team_state_facade
    from products.warehouse_sources.backend.facade.ducklake import list_ducklake_imported_tables

    locators: dict[str, TrinoTableLocator] = {
        "events": (catalog_name, "posthog", table_names.events_table),
        "persons": (catalog_name, "posthog", table_names.persons_table),
    }

    if table_names.groups_table is not None:
        for logical_name in ("groups", "raw_groups"):
            locators[logical_name] = (catalog_name, "posthog", table_names.groups_table)

    model_schema = ducklake_data_modeling_schema(team_id)
    materialized_models = list(
        DataWarehouseSavedQuery.objects.filter(team_id=team_id, is_materialized=True, table__isnull=False).exclude(
            deleted=True
        )
    )
    model_table_names = get_data_modeling_table_names(team_id, [saved_query.id for saved_query in materialized_models])
    for saved_query in materialized_models:
        if database.has_table(saved_query.name):
            locators[saved_query.name] = (
                catalog_name,
                model_schema,
                model_table_names[saved_query.id],
            )

    naming_version = team_state_facade.data_imports_table_naming_version(team_id)
    for table in list_ducklake_imported_tables(team_id, naming_version):
        locator = (catalog_name, table_names.data_imports_schema, table.physical_table_name)
        for logical_name in table.logical_table_names:
            if database.has_table(logical_name):
                locators[logical_name] = locator

    for name, locator in _external_trino_locators_for_warehouse_tables(team_id).items():
        if name not in locators and database.has_table(name):
            locators[name] = locator

    return locators


def _external_trino_locators_for_warehouse_tables(team_id: int) -> dict[str, TrinoTableLocator]:
    """Map self-managed Delta warehouse tables to the external Trino table that reads the same files.

    A warehouse table keeps its name and its ClickHouse ``s3()`` read; only Trino reads it through the
    tenant's catalog. A location that several external tables share is ambiguous and maps nothing.
    """
    from django.db.models import Q

    from products.data_warehouse.backend.facade.sources import (
        DIRECT_TRINO_CATALOG_OPTION,
        DIRECT_TRINO_LOCATION_OPTION,
        DIRECT_TRINO_SCHEMA_OPTION,
        DIRECT_TRINO_TABLE_OPTION,
        DIRECT_TRINO_URL_PATTERN,
    )
    from products.warehouse_sources.backend.facade.models import DataWarehouseTable
    from products.warehouse_sources.backend.facade.types import DataWarehouseTableFormat

    tables = (
        DataWarehouseTable.objects.queryable()
        .filter(team_id=team_id)
        .filter(
            Q(external_data_source__isnull=True, format=DataWarehouseTableFormat.Delta)
            | Q(
                external_data_source__access_method=ExternalDataSourceAccessMethod.DIRECT,
                url_pattern=DIRECT_TRINO_URL_PATTERN,
                **{f"options__{DIRECT_TRINO_LOCATION_OPTION}__isnull": False},
            )
        )
        .select_related("external_data_source")
    )
    external_by_location: dict[str, list[TrinoTableLocator]] = {}
    warehouse_roots: dict[str, str] = {}
    for table in tables:
        source = table.external_data_source
        if source is None:
            root = delta_table_root(table.url_pattern or "")
            if root is not None:
                warehouse_roots[table.name] = root
            continue
        options = table.options if isinstance(table.options, dict) else {}
        catalog = options.get(DIRECT_TRINO_CATALOG_OPTION)
        schema = options.get(DIRECT_TRINO_SCHEMA_OPTION)
        table_name = options.get(DIRECT_TRINO_TABLE_OPTION)
        location = options.get(DIRECT_TRINO_LOCATION_OPTION)
        if (
            not source.is_dynamic_managed_warehouse
            or not isinstance(catalog, str)
            or not is_managed_trino_external_catalog(catalog)
            or not isinstance(schema, str)
            or not isinstance(table_name, str)
            or not isinstance(location, str)
        ):
            continue
        external_by_location.setdefault(location, []).append((catalog, schema, table_name))

    locators: dict[str, TrinoTableLocator] = {}
    for name, root in warehouse_roots.items():
        candidates = external_by_location.get(root, [])
        if len(candidates) == 1:
            locators[name] = candidates[0]
        elif candidates:
            logger.warning("Warehouse table %s matches %d external Trino tables; mapping none", name, len(candidates))
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
