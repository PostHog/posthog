"""Find a schema's history table and the naming it was created with."""

from __future__ import annotations

from uuid import UUID

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
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import (
    build_table_name,
    resolve_table_and_folder_names,
)


class HistoryTableNameTakenError(Exception):
    """Another table of the source has the name a new history table would take.

    The two would share one name and one storage folder, so each sync would overwrite the other.
    """


def not_another_schemas_table(tables: QuerySet[DataWarehouseTable], schema_id: UUID) -> QuerySet[DataWarehouseTable]:
    """Drop tables another schema syncs into.

    A source table can carry a history table's name, as `orders_cdc` next to `orders` does. A history
    table is linked to no schema, or to its own schema in `cdc_only` mode.
    """
    return tables.filter(Q(externaldataschema__isnull=True) | Q(externaldataschema__id=schema_id)).distinct()


def kept_history_naming(schema: ExternalDataSchema) -> HistoryNaming | None:
    """The naming of the history table the schema's mode writes, or None when it writes none."""
    return history_naming(schema) if is_history_table_mode(schema.cdc_table_mode) else None


def history_naming(schema: ExternalDataSchema) -> HistoryNaming:
    """The naming of the schema's history table, read from its registration.

    A schema without a history table gets `HISTORY_NAMING`, which is the naming its history table will
    be created with. A table under the legacy name predates the stamp and the marker, so it keeps the
    legacy naming with or without them. Raises `HistoryTableNameTakenError` when the new name belongs to
    another table of the source.
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
    if LEGACY_HISTORY_NAMING in by_naming:
        return LEGACY_HISTORY_NAMING
    existing = by_naming.get(HISTORY_NAMING)
    if existing is not None and existing.has_ph_history_naming:
        return HISTORY_NAMING
    new_name = next(name for name, naming in names.items() if naming == HISTORY_NAMING)
    new_folder = NamingConvention.normalize_identifier(companion_resource_name(schema.name, HISTORY_NAMING))
    if existing is not None:
        raise HistoryTableNameTakenError(f"{new_name} is another table of this source")
    # A sibling that neither syncs nor holds a table writes nothing there. Turning its sync on later
    # is refused by `is_another_schemas_history_table`.
    siblings = (
        ExternalDataSchema.objects.filter(team_id=schema.team_id, source_id=source.id, deleted=False)
        .filter(Q(should_sync=True) | Q(table__isnull=False))
        .exclude(id=schema.id)
    )
    for sibling in siblings:
        sibling_names = resolve_table_and_folder_names(sibling.name, sibling.resolved_s3_folder_name)
        if (
            sibling_names.folder_name == new_folder
            or build_table_name(source, sibling_names.table_storage_name) == new_name
        ):
            raise HistoryTableNameTakenError(f"{new_name} is the table of schema {sibling.name}")
    return HISTORY_NAMING


def history_naming_unless_taken(schema: ExternalDataSchema) -> HistoryNaming | None:
    """`history_naming`, or None when the new name belongs to another table of the source."""
    try:
        return history_naming(schema)
    except HistoryTableNameTakenError:
        return None


def is_another_schemas_history_table(schema: ExternalDataSchema) -> bool:
    """Whether the schema's own table name already belongs to the history table of another schema."""
    name = build_table_name(schema.source, schema.name)
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


def history_tables(source: ExternalDataSource) -> QuerySet[DataWarehouseTable]:
    """The source's registered history tables.

    One that stopped syncing before the marker existed, such as one whose schema dropped its history
    table, carries only the legacy name of its schema. A legacy name that is also a schema's own table
    name, as `orders_cdc` next to `orders` is, stays out unless the marker says otherwise.
    """
    own_names = {build_table_name(source, name) for name in _schema_names(source)}
    return DataWarehouseTable.objects.filter(
        team_id=source.team_id, external_data_source_id=source.id, deleted=False
    ).filter(Q(options__history_table=True) | Q(name__in=_legacy_history_names(source) - own_names))


def history_table_ids(source: ExternalDataSource) -> list[UUID]:
    return list(history_tables(source).values_list("id", flat=True))


def history_table_name(schema: ExternalDataSchema) -> str | None:
    """The name of the history table the schema's mode writes, or None when it writes none or cannot."""
    try:
        naming = kept_history_naming(schema)
    except HistoryTableNameTakenError:
        return None
    return None if naming is None else build_table_name(schema.source, companion_resource_name(schema.name, naming))
