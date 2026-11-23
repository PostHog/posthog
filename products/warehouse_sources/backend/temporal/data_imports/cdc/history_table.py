"""Find a schema's history table and the naming it was created with."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Q, QuerySet

from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.activity_logging.model_activity import get_current_user, get_was_impersonated

from products.warehouse_sources.backend.facade.contracts import HistoryTableDropRefusedError, LegacyHistoryTableError
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
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import (
    build_table_name,
    resolve_table_and_folder_names,
)
from products.warehouse_sources.backend.temporal.data_imports.query_folder_state import QUERY_FOLDER_STATE_KEY
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


def registered_history_table(schema: ExternalDataSchema) -> DataWarehouseTable | None:
    """The schema's registered history table, whether or not its mode still writes it."""
    registered = _registered_history(schema)
    return registered[0] if registered is not None else None


def _registered_history(schema: ExternalDataSchema) -> tuple[DataWarehouseTable, HistoryNaming] | None:
    tables = _registered_history_tables(schema)
    naming = _naming_of_registered(tables)
    if naming is None:
        return None
    table = tables[naming]
    # The naming lookup also accepts an unmarked legacy name, which an unrelated table can carry. A delete
    # can't be undone, so it takes only a table the sync marked.
    if not table.is_history_table:
        return None
    return table, naming


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


HISTORY_STAGING_SUFFIX = "_ph_staging"

HISTORY_TABLE_STILL_WRITTEN_ERROR = (
    "This table still writes its history table. Switch it to the consolidated table only, or off change data "
    "capture, before you delete the history table."
)
HISTORY_TABLE_CHECK_FAILED_ERROR = (
    "PostHog couldn't check whether a sync of this table is still running. Try again in a few minutes."
)
HISTORY_TABLE_SYNC_IN_FLIGHT_ERROR = (
    "A sync of this table is still running and could still write to its history table. Try again once it "
    "finishes, or cancel it first."
)


def assert_history_table_droppable(schema: ExternalDataSchema, *, keeps_history: bool) -> None:
    """Raise `HistoryTableDropRefusedError` while the schema's history table can still be written.

    `keeps_history` is whether the schema's mode writes the table, after a pending save when there is one.
    A sync that read an earlier mode can still write the table while its workflow runs, and its batches can
    still be in the load queue after that.
    """
    # Deferred: source_manager pulls in the pipeline.
    from products.warehouse_sources.backend.temporal.data_imports.cdc.snapshot_lane import (  # noqa: PLC0415
        running_sync_workflow_id,
    )
    from products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager import (  # noqa: PLC0415
        has_queued_batches,
    )

    if keeps_history:
        raise HistoryTableDropRefusedError(HISTORY_TABLE_STILL_WRITTEN_ERROR)
    try:
        in_flight = running_sync_workflow_id(schema) is not None or has_queued_batches(schema)
    except Exception as e:
        capture_exception(e)
        raise HistoryTableDropRefusedError(HISTORY_TABLE_CHECK_FAILED_ERROR) from e
    if in_flight:
        raise HistoryTableDropRefusedError(HISTORY_TABLE_SYNC_IN_FLIGHT_ERROR)


def drop_history_table(
    schema: ExternalDataSchema, *, rebuilding: bool = False, keep_record: bool | None = None
) -> DataWarehouseTable | None:
    """Delete the schema's registered history table: its files, its record and the schema's state for it.

    `rebuilding` is for a delete a new mask asks for, so the mode alone does not refuse it. A sync in flight
    still does. `keep_record` (default: `rebuilding`) deletes the files but keeps the record, for a schema that
    keeps history: the rebuild registers the same table again, and the access rules set on it stay in force.

    Returns the dropped table, or None when the schema has no history table. Raises
    `HistoryTableDropRefusedError` while the schema's mode writes the table, or while a sync could still
    write to it. A storage error propagates and leaves the record, so a retry deletes the rest. A later
    switch back to a history mode then creates a new history table under the naming new tables get at
    that time.
    """
    registered = _registered_history(schema)
    if registered is None:
        return None
    table, naming = registered
    keep = rebuilding if keep_record is None else keep_record
    folder_name = NamingConvention.normalize_identifier(companion_resource_name(schema.name, naming))
    staging_folder_name = NamingConvention.normalize_identifier(
        companion_resource_name(schema.name, naming) + HISTORY_STAGING_SUFFIX
    )
    query_folder_prefix = f"{folder_name}__query"
    # Every mode save takes this row lock, so holding it from the checks until the record goes keeps a
    # switch back to history from landing while the files are deleted. A storage error rolls back with
    # the record still in place, so a retry deletes the rest.
    with transaction.atomic():
        locked = ExternalDataSchema.objects.select_for_update().get(id=schema.id, team_id=schema.team_id)
        assert_history_table_droppable(locked, keeps_history=locked.keeps_history and not rebuilding)
        _delete_history_files(schema, folder_name, staging_folder_name)
        config = locked.sync_type_config or {}
        if not keep:
            config.pop(HISTORY_NAMING_OPTION, None)
        states = config.get(QUERY_FOLDER_STATE_KEY)
        if isinstance(states, dict):
            states.pop(query_folder_prefix, None)
        locked.sync_type_config = config
        update_fields = ["sync_type_config", "updated_at"]
        # cdc_only links the schema to its history table.
        if locked.table_id == table.id and not keep:
            locked.table = None
            # The table's access rules go with it, so its source's rules must not take over for a live query.
            locked.live_query_enabled = False
            update_fields.extend(["table", "live_query_enabled"])
        locked.save(update_fields=update_fields, skip_activity_log=True)
        if not keep:
            table.soft_delete()
        # As the table view logs a deleted table: the name only, because a reader may be denied the table.
        log_activity(
            organization_id=table.team.organization_id,
            team_id=table.team_id,
            user=get_current_user(),
            was_impersonated=get_was_impersonated(),
            item_id=table.id,
            scope="DataWarehouseTable",
            activity="updated" if keep else "deleted",
            detail=Detail(
                name=table.name,
                changes=[Change(type="DataWarehouseTable", field="data", action="deleted")] if keep else None,
            ),
        )
    schema.sync_type_config = locked.sync_type_config
    schema.table = locked.table
    return table


def purge_history_staging(schema: ExternalDataSchema) -> bool:
    """Delete the rows an incremental history lane staged, whether or not a history table is registered yet.

    Finalize publishes every staged row, so rows staged before a mask would reach a later history table with
    the values it hides. Raises `HistoryTableDropRefusedError` while a sync could still write to the staging
    table. Returns whether there was one.
    """
    from products.data_warehouse.backend.facade.api import get_s3_client  # noqa: PLC0415

    staging_folder_name = NamingConvention.normalize_identifier(
        companion_resource_name(schema.name, HISTORY_NAMING) + HISTORY_STAGING_SUFFIX
    )
    s3 = get_s3_client()
    s3.invalidate_cache()
    try:
        entries = s3.ls(f"{settings.BUCKET_URL}/{schema.folder_path()}", detail=False)
    except FileNotFoundError:
        return False
    targets = [entry for entry in entries if entry.rstrip("/").rsplit("/", 1)[-1] == staging_folder_name]
    if not targets:
        return False
    with transaction.atomic():
        locked = ExternalDataSchema.objects.select_for_update().get(id=schema.id, team_id=schema.team_id)
        assert_history_table_droppable(locked, keeps_history=False)
        s3.rm(targets, recursive=True)
    return True


def _delete_history_files(schema: ExternalDataSchema, folder_name: str, staging_folder_name: str) -> None:
    """Delete the history table's Delta folder, its `<table>__query*` copies and its staging table."""
    from products.data_warehouse.backend.facade.api import get_s3_client  # noqa: PLC0415

    s3 = get_s3_client()
    s3.invalidate_cache()
    try:
        entries = s3.ls(f"{settings.BUCKET_URL}/{schema.folder_path()}", detail=False)
    except FileNotFoundError:
        return
    # The folder holds only this schema's tables, so the prefix match can't reach another table's copies.
    targets = [
        entry
        for entry in entries
        if (leaf := entry.rstrip("/").rsplit("/", 1)[-1]) in (folder_name, staging_folder_name)
        or leaf.startswith(f"{folder_name}__query")
    ]
    if targets:
        s3.rm(targets, recursive=True)
