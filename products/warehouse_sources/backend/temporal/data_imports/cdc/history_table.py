"""Find a schema's history table and the naming it was created with."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from django.conf import settings
from django.db.models import Q, QuerySet

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import (
    HISTORY_NAMING,
    LEGACY_HISTORY_NAMING,
    HistoryNaming,
    companion_resource_name,
    is_history_table_mode,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import (
    build_table_name,
    resolve_table_and_folder_names,
)


class HistoryTableNameTakenError(Exception):
    """Another table of the source already has the catalog name a new history table would take.

    Two registrations under one name hide one of the tables from queries, and the companion registration
    would take the other table's record.
    """


def not_another_schemas_table(tables: QuerySet[DataWarehouseTable], schema_id: UUID) -> QuerySet[DataWarehouseTable]:
    """Drop tables another schema syncs into.

    A source table can carry a history table's name, as `orders_cdc` next to `orders` does. A history
    table is linked to no schema, or to its own schema in `cdc_only` mode.
    """
    return tables.filter(Q(externaldataschema__isnull=True) | Q(externaldataschema__id=schema_id)).distinct()


def new_history_naming() -> HistoryNaming:
    """The naming a history table created now gets."""
    return HISTORY_NAMING if settings.DATA_WAREHOUSE_PH_HISTORY_NAMING else LEGACY_HISTORY_NAMING


def kept_history_naming(schema: ExternalDataSchema) -> HistoryNaming | None:
    """The naming of the history table the schema's mode writes, or None when it writes none."""
    return history_naming(schema) if is_history_table_mode(schema.cdc_table_mode) else None


def registered_history_naming(schema: ExternalDataSchema) -> HistoryNaming | None:
    """The naming of the schema's registered history table, or None when it has none yet.

    A stamped `_history` table wins over a table under the legacy name, which a source table can also
    carry. A legacy table predates the stamp and the marker, so its name is all it has.
    """
    source = schema.source
    names = {
        build_table_name(source, companion_resource_name(schema.name, naming)): naming
        for naming in (HISTORY_NAMING, LEGACY_HISTORY_NAMING)
    }
    tables = not_another_schemas_table(
        DataWarehouseTable.objects.filter(
            team_id=schema.team_id, external_data_source_id=source.id, deleted=False, name__in=names
        ),
        schema.id,
    )
    by_naming = {names[table.name]: table for table in tables}
    current = by_naming.get(HISTORY_NAMING)
    if current is not None and current.has_ph_history_naming:
        return HISTORY_NAMING
    return LEGACY_HISTORY_NAMING if LEGACY_HISTORY_NAMING in by_naming else None


def history_naming(schema: ExternalDataSchema) -> HistoryNaming:
    """The naming of the schema's history table, read from its registration, else `new_history_naming`.

    Raises `HistoryTableNameTakenError` when a new history table would take the catalog name of another
    table of the source.
    """
    registered = registered_history_naming(schema)
    if registered is not None:
        return registered
    naming = new_history_naming()
    source = schema.source
    new_name = build_table_name(source, companion_resource_name(schema.name, naming))
    if DataWarehouseTable.objects.filter(
        team_id=schema.team_id, external_data_source_id=source.id, deleted=False, name=new_name
    ).exists():
        raise HistoryTableNameTakenError(f"{new_name} is already the name of another table of this source")
    # A sibling that neither syncs nor holds a table registers nothing under the name. Turning its sync on
    # later is refused by `is_another_schemas_history_table`.
    siblings = (
        ExternalDataSchema.objects.filter(team_id=schema.team_id, source_id=source.id, deleted=False)
        .filter(Q(should_sync=True) | Q(table__isnull=False))
        .exclude(id=schema.id)
    )
    for sibling in siblings:
        sibling_names = resolve_table_and_folder_names(sibling.name, sibling.resolved_s3_folder_name)
        if build_table_name(source, sibling_names.table_storage_name) == new_name:
            raise HistoryTableNameTakenError(f"{new_name} is already the name of another table of this source")
    return naming


def new_history_names_taken(
    source: ExternalDataSource, history_schema_names: Iterable[str], synced_schema_names: Iterable[str]
) -> list[str]:
    """The schemas of a new source whose `_history` table would take the catalog name of a synced schema."""
    if new_history_naming() != HISTORY_NAMING:
        return []
    taken = {build_table_name(source, name) for name in synced_schema_names}
    return sorted(
        name
        for name in history_schema_names
        if build_table_name(source, companion_resource_name(name, HISTORY_NAMING)) in taken
    )


def history_naming_unless_taken(schema: ExternalDataSchema) -> HistoryNaming | None:
    """`history_naming`, or None when the new name belongs to another table of the source."""
    try:
        return history_naming(schema)
    except HistoryTableNameTakenError:
        return None


def is_another_schemas_history_table(schema: ExternalDataSchema) -> bool:
    """Whether the schema's own table name belongs to the history table of another schema.

    A sibling that keeps history counts before its history table is registered, which happens only after
    its first snapshot loads.
    """
    name = build_table_name(schema.source, schema.name)
    siblings = ExternalDataSchema.objects.filter(
        team_id=schema.team_id, source_id=schema.source_id, deleted=False, sync_type=ExternalDataSchema.SyncType.CDC
    ).exclude(id=schema.id)
    if any(history_table_name(sibling) == name for sibling in siblings):
        return True
    taken = (
        DataWarehouseTable.objects.filter(
            team_id=schema.team_id, external_data_source_id=schema.source_id, deleted=False, name=name
        )
        .exclude(externaldataschema__id=schema.id)
        .first()
    )
    if taken is None:
        return False
    return taken.is_history_table or name in _legacy_history_names(schema.source, exclude_schema_id=schema.id)


def _schema_names(source: ExternalDataSource, *, exclude_schema_id: UUID | None = None) -> list[str]:
    schemas = ExternalDataSchema.objects.filter(team_id=source.team_id, source_id=source.id, deleted=False)
    if exclude_schema_id is not None:
        schemas = schemas.exclude(id=exclude_schema_id)
    return list(schemas.values_list("name", flat=True))


def _legacy_history_names(source: ExternalDataSource, *, exclude_schema_id: UUID | None = None) -> set[str]:
    return {
        build_table_name(source, companion_resource_name(name, LEGACY_HISTORY_NAMING))
        for name in _schema_names(source, exclude_schema_id=exclude_schema_id)
    }


def history_tables(source: ExternalDataSource) -> list[DataWarehouseTable]:
    """The source's registered history tables.

    One that stopped syncing before the marker existed, such as one whose schema dropped its history
    table, carries only the legacy name of its schema. A table under a legacy name that a schema of that
    very name syncs into, as `orders_cdc` next to `orders` does, is that schema's own table.
    """
    candidates = DataWarehouseTable.objects.filter(
        team_id=source.team_id, external_data_source_id=source.id, deleted=False
    ).filter(Q(options__history_table=True) | Q(name__in=_legacy_history_names(source)))
    own_tables = {
        table_id: build_table_name(source, name)
        for table_id, name in ExternalDataSchema.objects.filter(
            team_id=source.team_id, source_id=source.id, deleted=False, table_id__isnull=False
        ).values_list("table_id", "name")
    }
    return [table for table in candidates if table.is_history_table or own_tables.get(table.id) != table.name]


def history_table_ids(source: ExternalDataSource) -> list[UUID]:
    return [table.id for table in history_tables(source)]


def history_table_name(schema: ExternalDataSchema) -> str | None:
    """The name of the history table the schema's mode writes, or None when it writes none.

    Skips the name check of `history_naming`, so a list of schemas costs one query per history table.
    """
    if not schema.keeps_history:
        return None
    naming = registered_history_naming(schema) or new_history_naming()
    return build_table_name(schema.source, companion_resource_name(schema.name, naming))
