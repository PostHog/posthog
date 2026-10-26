"""Find a schema's history table and the naming it was created with."""

from __future__ import annotations

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


def kept_history_naming(schema: ExternalDataSchema) -> HistoryNaming | None:
    """The naming of the history table the schema's mode writes, or None when it writes none."""
    return history_naming(schema) if is_history_table_mode(schema.cdc_table_mode) else None


def history_naming(schema: ExternalDataSchema) -> HistoryNaming:
    """The naming of the schema's history table, read from its registration.

    A schema without a history table gets `HISTORY_NAMING`, which is the naming its history table will
    be created with. A table under the legacy name predates the stamp, so it keeps the legacy naming.
    Raises `HistoryTableNameTakenError` when the new name belongs to another table of the source.
    """
    source = schema.source
    names = {
        build_table_name(source, companion_resource_name(schema.name, naming)): naming
        for naming in (HISTORY_NAMING, LEGACY_HISTORY_NAMING)
    }
    tables = DataWarehouseTable.objects.filter(
        team_id=schema.team_id, external_data_source_id=source.id, deleted=False, name__in=names
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


def is_another_schemas_history_table(schema: ExternalDataSchema) -> bool:
    """Whether the schema's own table name already belongs to the history table of another schema."""
    return (
        DataWarehouseTable.objects.filter(
            team_id=schema.team_id,
            external_data_source_id=schema.source_id,
            deleted=False,
            name=build_table_name(schema.source, schema.name),
            options__history_table=True,
        )
        .exclude(externaldataschema__id=schema.id)
        .exists()
    )


def history_tables(source: ExternalDataSource) -> QuerySet[DataWarehouseTable]:
    """The source's registered history tables.

    One registered before the marker existed carries only the legacy name of its CDC schema.
    """
    cdc_schema_names = ExternalDataSchema.objects.filter(
        team_id=source.team_id, source_id=source.id, sync_type=ExternalDataSchema.SyncType.CDC, deleted=False
    ).values_list("name", flat=True)
    legacy_names = [
        build_table_name(source, companion_resource_name(name, LEGACY_HISTORY_NAMING)) for name in cdc_schema_names
    ]
    return DataWarehouseTable.objects.filter(
        team_id=source.team_id, external_data_source_id=source.id, deleted=False
    ).filter(Q(options__history_table=True) | Q(name__in=legacy_names))


def history_table_name(schema: ExternalDataSchema) -> str | None:
    """The name of the history table the schema's mode writes, or None when it writes none or cannot."""
    try:
        naming = kept_history_naming(schema)
    except HistoryTableNameTakenError:
        return None
    return None if naming is None else build_table_name(schema.source, companion_resource_name(schema.name, naming))
