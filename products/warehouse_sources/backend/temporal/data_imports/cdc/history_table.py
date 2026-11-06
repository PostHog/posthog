"""Find a schema's history table and the naming it was created with."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from django.db.models import Q, QuerySet

from products.warehouse_sources.backend.facade.contracts import LegacyHistoryTableError
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import HISTORY_NAMING_OPTION, PH_HISTORY_NAMING, DataWarehouseTable
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
from products.warehouse_sources.backend.temporal.data_imports.schema_flags import is_source_flag_enabled

# New history tables are named `<table>_history` with `_ph_valid_from` / `_ph_valid_to` while this flag is on
# for the source. Keep it off until every loader reads the validity names from the batch: an older loader
# appends such a batch without closing the open versions.
PH_HISTORY_NAMING_FLAG = "warehouse-ph-history-naming"
_LEGACY_HISTORY_NAMING = "legacy"


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


def new_history_naming(source: ExternalDataSource) -> HistoryNaming:
    """The naming a history table of this source created now gets."""
    return HISTORY_NAMING if is_source_flag_enabled(source, PH_HISTORY_NAMING_FLAG) else LEGACY_HISTORY_NAMING


def pin_history_naming(sync_type_config: dict[str, Any], naming: HistoryNaming) -> None:
    """Record on the schema the naming its columns were checked against.

    The flag can change, or fail to evaluate, before the history table is registered. Capture would then
    refuse a source column the API accepted.
    """
    sync_type_config[HISTORY_NAMING_OPTION] = PH_HISTORY_NAMING if naming == HISTORY_NAMING else _LEGACY_HISTORY_NAMING


def pinned_history_naming(schema: ExternalDataSchema) -> HistoryNaming | None:
    value = (schema.sync_type_config or {}).get(HISTORY_NAMING_OPTION)
    if value == PH_HISTORY_NAMING:
        return HISTORY_NAMING
    return LEGACY_HISTORY_NAMING if value == _LEGACY_HISTORY_NAMING else None


def kept_history_naming(schema: ExternalDataSchema) -> HistoryNaming | None:
    """The naming of the history table the schema's mode writes, or None when it writes none."""
    return history_naming(schema) if is_history_table_mode(schema.cdc_table_mode) else None


def registered_history_naming(schema: ExternalDataSchema) -> HistoryNaming | None:
    """The naming of the schema's registered history table, or None when it has none yet.

    A stamped `_history` table wins over a table under the legacy name, which a source table can also
    carry. A legacy table predates the stamp and the marker, so its name is all it has.
    """
    return _naming_of_registered(_registered_history_tables(schema))


def registered_stamped_history_table(schema: ExternalDataSchema) -> DataWarehouseTable | None:
    """The schema's registered `_history` table with the `_ph_` validity names, also once its mode stops writing it."""
    table = _registered_history_tables(schema).get(HISTORY_NAMING)
    return table if table is not None and table.has_ph_history_naming else None


def _registered_history_tables(schema: ExternalDataSchema) -> dict[HistoryNaming, DataWarehouseTable]:
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
    return {names[table.name]: table for table in tables}


def _naming_of_registered(tables_by_naming: dict[HistoryNaming, DataWarehouseTable]) -> HistoryNaming | None:
    current = tables_by_naming.get(HISTORY_NAMING)
    if current is not None and current.has_ph_history_naming:
        return HISTORY_NAMING
    return LEGACY_HISTORY_NAMING if LEGACY_HISTORY_NAMING in tables_by_naming else None


class SourceHistoryNamings:
    """Resolves the history naming of a source's schemas from one read of its schemas and tables."""

    def __init__(self, source: ExternalDataSource) -> None:
        self._source = source
        schemas = list(ExternalDataSchema.objects.filter(team_id=source.team_id, source_id=source.id, deleted=False))
        self._schema_ids_by_table: defaultdict[UUID, set[UUID]] = defaultdict(set)
        # A sibling that neither syncs nor holds a table registers nothing under its name. Turning its sync on
        # later is refused by `is_another_schemas_history_table`.
        self._synced_schema_ids_by_name: defaultdict[str, set[UUID]] = defaultdict(set)
        for schema in schemas:
            if schema.table_id is not None:
                self._schema_ids_by_table[schema.table_id].add(schema.id)
            if schema.should_sync or schema.table_id is not None:
                names = resolve_table_and_folder_names(schema.name, schema.resolved_s3_folder_name)
                self._synced_schema_ids_by_name[build_table_name(source, names.table_storage_name)].add(schema.id)
        self._tables_by_name: defaultdict[str, list[DataWarehouseTable]] = defaultdict(list)
        for table in DataWarehouseTable.objects.filter(
            team_id=source.team_id, external_data_source_id=source.id, deleted=False
        ):
            self._tables_by_name[table.name].append(table)
        self._new_naming: HistoryNaming | None = None

    def naming(self, schema: ExternalDataSchema) -> HistoryNaming:
        """The naming of the schema's history table: its registration, else its pin, else `new_history_naming`.

        Raises `HistoryTableNameTakenError` when a new history table would take the catalog name of another
        table of the source.
        """
        registered = self._registered(schema)
        if registered is not None:
            return registered
        naming = pinned_history_naming(schema) or self._naming_for_new_tables()
        self._refuse_taken_name(schema, naming)
        return naming

    def incremental_naming(self, schema: ExternalDataSchema) -> HistoryNaming:
        """The naming of an incremental schema's history table, which is `HISTORY_NAMING` whatever the flag or pin.

        Raises `LegacyHistoryTableError` when the schema's registered history table uses the legacy naming, and
        `HistoryTableNameTakenError` as `naming` does.
        """
        tables = self._registered_tables(schema)
        registered = _naming_of_registered(tables)
        # An unmarked `_cdc` table can be an ordinary source table, and incremental history never writes that name.
        if registered == LEGACY_HISTORY_NAMING and tables[LEGACY_HISTORY_NAMING].is_history_table:
            legacy_name = tables[LEGACY_HISTORY_NAMING].name
            raise LegacyHistoryTableError(
                f"{schema.name} has an older history table, {legacy_name}, that incremental syncs can't add to. "
                f"Choose the consolidated table only, or sync {schema.name} with change data capture."
            )
        if registered != HISTORY_NAMING:
            self._refuse_taken_name(schema, HISTORY_NAMING)
        return HISTORY_NAMING

    def _refuse_taken_name(self, schema: ExternalDataSchema, naming: HistoryNaming) -> None:
        new_name = build_table_name(self._source, companion_resource_name(schema.name, naming))
        if self._tables_by_name.get(new_name) or self._synced_schema_ids_by_name.get(new_name, set()) - {schema.id}:
            raise HistoryTableNameTakenError(f"{new_name} is already the name of another table of this source")

    def naming_unless_taken(self, schema: ExternalDataSchema) -> HistoryNaming | None:
        try:
            return self.naming(schema)
        except HistoryTableNameTakenError:
            return None

    def _registered(self, schema: ExternalDataSchema) -> HistoryNaming | None:
        return _naming_of_registered(self._registered_tables(schema))

    def _registered_tables(self, schema: ExternalDataSchema) -> dict[HistoryNaming, DataWarehouseTable]:
        # A table another schema syncs into is that schema's own, as `orders_cdc` next to `orders` is.
        return {
            naming: table
            for naming in (HISTORY_NAMING, LEGACY_HISTORY_NAMING)
            for table in self._tables_by_name.get(
                build_table_name(self._source, companion_resource_name(schema.name, naming)), []
            )
            if self._schema_ids_by_table.get(table.id, set()) <= {schema.id}
        }

    def _naming_for_new_tables(self) -> HistoryNaming:
        if self._new_naming is None:
            self._new_naming = new_history_naming(self._source)
        return self._new_naming


def history_naming(schema: ExternalDataSchema) -> HistoryNaming:
    """`SourceHistoryNamings.naming` for one schema."""
    return SourceHistoryNamings(schema.source).naming(schema)


def incremental_history_naming(schema: ExternalDataSchema) -> HistoryNaming:
    """`SourceHistoryNamings.incremental_naming` for one schema."""
    return SourceHistoryNamings(schema.source).incremental_naming(schema)


def incremental_history_naming_unless_taken(schema: ExternalDataSchema) -> HistoryNaming | None:
    """`incremental_history_naming`, or None when the new name belongs to another table of the source."""
    try:
        return incremental_history_naming(schema)
    except HistoryTableNameTakenError:
        return None


def new_history_names_taken(
    source: ExternalDataSource,
    naming: HistoryNaming,
    history_schema_names: Iterable[str],
    synced_schema_names: Iterable[str],
) -> list[str]:
    """The schemas of a new source whose history table would take the catalog name of a synced schema."""
    taken = {build_table_name(source, name) for name in synced_schema_names}
    return sorted(
        name
        for name in history_schema_names
        if build_table_name(source, companion_resource_name(name, naming)) in taken
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
    source = schema.source
    name = build_table_name(
        source, resolve_table_and_folder_names(schema.name, schema.resolved_s3_folder_name).table_storage_name
    )
    siblings = ExternalDataSchema.objects.filter(
        team_id=schema.team_id,
        source_id=schema.source_id,
        deleted=False,
        sync_type__in=[ExternalDataSchema.SyncType.CDC, ExternalDataSchema.SyncType.INCREMENTAL],
    ).exclude(id=schema.id)
    # Only a sibling whose history name under some naming matches pays for the registration lookup.
    candidates = [
        sibling
        for sibling in siblings
        if any(
            build_table_name(source, companion_resource_name(sibling.name, naming)) == name
            for naming in (HISTORY_NAMING, LEGACY_HISTORY_NAMING)
        )
    ]
    if any(history_table_name(sibling) == name for sibling in candidates):
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
    return taken.is_history_table or name in _legacy_history_names(source, exclude_schema_id=schema.id)


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


def history_table_name(schema: ExternalDataSchema) -> str | None:
    """The name of the history table the schema's mode writes, or None when it writes none.

    Skips the name check of `history_naming`, so a list of schemas costs one query per history table.
    """
    if not schema.keeps_history:
        return None
    if schema.is_incremental:
        naming = HISTORY_NAMING
    else:
        naming = registered_history_naming(schema) or pinned_history_naming(schema) or new_history_naming(schema.source)
    return build_table_name(schema.source, companion_resource_name(schema.name, naming))
