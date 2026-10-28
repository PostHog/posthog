from abc import abstractmethod
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, ClassVar, Generic, NoReturn, Optional

import pyarrow as pa
from botocore.exceptions import ClientError
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.util import validate_warehouse_table_url_pattern
from products.warehouse_sources.backend.temporal.data_imports.schema_flags import (
    REPLACE_ROWS_BY_FILE_FLAG,
    is_schema_flag_enabled,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import ConfigType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import CursorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.file_parsing import FILE_MODIFIED_AT_COLUMN
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.config import (
    DiscoveryOptions,
    FileFormat,
    StoreConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.delta import (
    DELTA_VERSION_COLUMN,
    ObjectStorageDeltaCursor,
    iter_delta_tables,
    plan_delta_read,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.discovery import (
    TableDefinition,
    group_tables,
    resolve_file_format,
    resolve_table_files,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.errors import (
    ACCESS_DENIED_ERROR,
    BLOCKED_LOCATION_ERROR,
    DELTA_UNSUPPORTED_ERROR,
    FILE_PARSE_ERROR,
    INVALID_CONFIG_ERROR,
    NO_IMPORTABLE_FILES_ERROR,
    NO_SUCH_BUCKET_ERROR,
    NO_TABLE_FILES_ERROR,
    TOO_MANY_FILES_ERROR,
    WRONG_REGION_ERROR,
    ObjectStorageError,
    translate_storage_error,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.filesystem import (
    ObjectStore,
    StoredObject,
    open_store,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.formats import (
    iter_file_tables,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.incremental import (
    FILE_PRIMARY_KEYS,
    READ_ALL,
    FileSelection,
    plan_mirror,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.self_managed import (
    SelfManagedCredential,
    SelfManagedLocation,
    StorageService,
    UnmappableTableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.settings import (
    CHUNK_SIZE_BYTES,
    MAX_DISCOVERY_OBJECTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    incremental_field,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import probe_status_message
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.types import ExternalDataSchemaSyncType, IncrementalFieldType


def _raise_translated(error: Exception, location: str) -> NoReturn:
    translated = translate_storage_error(error, location)
    if translated is error:
        raise error
    raise translated from error


def _http_status(error: BaseException) -> int | None:
    """The HTTP status of the botocore error behind an s3fs error, if there is one."""
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, ClientError):
            status = current.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if isinstance(status, int):
                return status
        current = current.__cause__
    return None


def validate_store_location(config: StoreConfig) -> None:
    """Apply the checks a self-managed warehouse table URL gets: https, no internal hosts, and no
    bucket that PostHog itself owns."""
    is_valid, error = validate_warehouse_table_url_pattern(config.location_url)
    if not is_valid:
        raise ObjectStorageError(f"{BLOCKED_LOCATION_ERROR}: {error}")


class ObjectStorageSource(SimpleSource[ConfigType], CursorSource[ObjectStorageDeltaCursor], Generic[ConfigType]):
    """Imports the files a bucket URL selects: CSV, JSON Lines and Parquet files, and Delta tables.

    A full refresh reads each table in full, so the table matches the bucket at the time of the sync.
    The incremental and append sync types read only the files modified since the last sync. An append
    never removes rows, so the rows of a file deleted from the bucket stay in the table. An incremental
    sync with `REPLACE_ROWS_BY_FILE_FLAG` on also deletes the rows of a deleted file, and a changed file
    replaces its rows. Without the flag it merges on the file and row number and keeps the rows of
    deleted files. An append sync of a Delta table reads only the data files committed since the
    version of the last sync. An incremental sync of a Delta table also replaces the rows of each data
    file that a commit removed, so deletes, updates, merges and compactions reach the table. Without
    the flag it rebuilds the table on every run.
    """

    @abstractmethod
    def object_store_config(self, config: ConfigType) -> StoreConfig: ...

    @abstractmethod
    def discovery_options(self, config: ConfigType) -> DiscoveryOptions: ...

    # The service whose self-managed warehouse tables this source can take over.
    self_managed_service: ClassVar[StorageService]

    @abstractmethod
    def self_managed_connection_inputs(
        self, location: SelfManagedLocation, credential: SelfManagedCredential
    ) -> dict[str, Any]:
        """The job inputs that reach the table's bucket with the table's own credential."""

    def job_inputs_for_self_managed(
        self, location: SelfManagedLocation, credential: SelfManagedCredential
    ) -> dict[str, Any]:
        """Job inputs for a source rooted at the bucket of a self-managed table.

        The inputs go through the same parsing and location checks as a source a user creates, so
        a credential or bucket the source would refuse is refused here too.
        """
        raw = {
            **self.self_managed_connection_inputs(location, credential),
            "file_format": "infer",
            "csv_allow_double_quotes": "true",
        }
        try:
            config = self.parse_config(raw)
            validate_store_location(self.object_store_config(config))
        except (ObjectStorageError, TypeError, ValueError) as e:
            raise UnmappableTableError(str(e)) from e
        return self.serialize_config(config)

    def cursor_class(self) -> type[ObjectStorageDeltaCursor]:
        return ObjectStorageDeltaCursor

    def open_store(self, store_config: StoreConfig) -> ObjectStore:
        """Re-check the location every time the stored credentials are about to be sent to it."""
        validate_store_location(store_config)
        return open_store(store_config)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            INVALID_CONFIG_ERROR: None,
            BLOCKED_LOCATION_ERROR: None,
            ACCESS_DENIED_ERROR: (
                "The storage provider rejected these credentials. Check the access key and secret, and that "
                "the key can list and read the bucket, then reconnect the source."
            ),
            NO_SUCH_BUCKET_ERROR: "The bucket doesn't exist. Check the bucket in the URL, then reconnect the source.",
            WRONG_REGION_ERROR: (
                "The bucket is in a different region. Fix the region in the URL, then reconnect the source."
            ),
            NO_TABLE_FILES_ERROR: (
                "The files behind this table are no longer in the bucket. Refresh the source's tables, or "
                "restore the files."
            ),
            TOO_MANY_FILES_ERROR: None,
            FILE_PARSE_ERROR: None,
            DELTA_UNSUPPORTED_ERROR: None,
        }

    def _discover(
        self, store: ObjectStore, config: ConfigType, logger: FilteringBoundLogger | None = None
    ) -> list[TableDefinition]:
        store_config = self.object_store_config(config)
        try:
            objects = store.list_objects(store_config.listing_prefix, MAX_DISCOVERY_OBJECTS)
        except Exception as e:
            _raise_translated(e, store_config.display_location)
        if len(objects) >= MAX_DISCOVERY_OBJECTS and logger is not None:
            logger.warning("Reached the object storage listing limit; later objects are ignored")
        root_name = store_config.prefix.rsplit("/", 1)[-1] if store_config.prefix else store_config.root_name
        return group_tables(
            objects,
            self.discovery_options(config),
            root_name=root_name,
            pattern=store_config.pattern,
            listing_prefix=store_config.listing_prefix,
            logger=logger,
        )

    def validate_credentials(
        self,
        config: ConfigType,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            store_config = self.object_store_config(config)
            tables = self._discover(self.open_store(store_config), config)
        except ObjectStorageError as e:
            return False, str(e)
        except OSError as e:
            # s3fs turns an S3 answer without a known error code, such as a bare 401 or a 500, into a plain OSError.
            status = _http_status(e)
            if status in (401, 403):
                return False, str(translate_storage_error(PermissionError(), store_config.display_location))
            message = probe_status_message(self.get_source_config.label or "The storage provider", status)
            if message is None:
                raise
            return False, message
        if not tables:
            return False, (
                f"{NO_IMPORTABLE_FILES_ERROR} in '{store_config.display_location}'. PostHog can read the bucket but "
                "found nothing to import there. Check the URL and the file format."
            )
        return True, None

    def get_schemas(
        self,
        config: ConfigType,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        store = self.open_store(self.object_store_config(config))
        requested = set(names) if names is not None else None
        return [
            _source_schema(table)
            for table in self._discover(store, config)
            if requested is None or table.name in requested
        ]

    def source_for_pipeline(self, config: ConfigType, inputs: SourceInputs) -> SourceResponse:
        store = self.open_store(self.object_store_config(config))
        table = TableDefinition.from_schema_metadata(inputs.schema_name, inputs.schema_metadata) or self._find_table(
            store, config, inputs.schema_name, inputs.logger
        )
        if table.kind == "delta":
            return self._delta_response(store, table, inputs)
        selection = FileSelection.from_inputs(inputs)
        if selection.merges and _mirrors_files(inputs):
            return self._mirrored_files_response(store, table, inputs, selection)

        def items() -> Iterator[pa.Table]:
            yield from iter_table(store, table, inputs.logger, selection)

        return SourceResponse(
            name=inputs.schema_name,
            items=items,
            # Only a merge needs a key. Without one, a full refresh replaces the table and an append adds to it.
            primary_keys=FILE_PRIMARY_KEYS if selection.merges else None,
            chunk_size_bytes=CHUNK_SIZE_BYTES,
            preserve_column_names=table.preserve_column_names,
        )

    def _mirrored_files_response(
        self, store: ObjectStore, table: TableDefinition, inputs: SourceInputs, selection: FileSelection
    ) -> SourceResponse:
        """An incremental read that also deletes the rows of deleted files and of rewritten files.

        The listing is made here and not in `items`, because the response has to name the files
        whose rows the run replaces before the first batch loads.
        """
        cursor_manager = self.get_cursor_manager(inputs)
        stored = cursor_manager.load()
        # Taken before listing, as in `iter_table`.
        listing_started_at = datetime.now(UTC)
        resolved = _resolve_files(store, table, inputs.logger)
        listed = [stored_file for stored_file in resolved.files if _file_format(resolved, stored_file) is not None]
        plan = plan_mirror(
            listed, selection, stored.files_digest if stored is not None else None, now=listing_started_at
        )

        def items() -> Iterator[pa.Table]:
            cursor_manager.stage(ObjectStorageDeltaCursor(files_digest=plan.digest))
            yield from _iter_files(store, resolved, plan.files, inputs.logger)

        return SourceResponse(
            name=inputs.schema_name,
            items=items,
            # A run with no scope reads no rows, but the pipeline still needs a key or a scope for an incremental run.
            primary_keys=FILE_PRIMARY_KEYS if plan.replace_scope is None else None,
            chunk_size_bytes=CHUNK_SIZE_BYTES,
            replace_scope=plan.replace_scope,
        )

    def _delta_response(self, store: ObjectStore, table: TableDefinition, inputs: SourceInputs) -> SourceResponse:
        cursor_manager = self.get_cursor_manager(inputs)
        appends = inputs.should_use_incremental_field
        by_file = appends and inputs.sync_type == ExternalDataSchemaSyncType.INCREMENTAL
        # Without the flag the loader can't delete by file, so an incremental sync rebuilds the
        # table from the snapshot on every run.
        stored = cursor_manager.load() if appends and (not by_file or _mirrors_files(inputs)) else None
        # The plan is made here and not in `items`, because the response has to say up front
        # whether the destination must be rebuilt.
        read = plan_delta_read(
            store.delta_uri(table.path),
            store.delta_storage_options,
            table.name,
            stored=stored,
            logger=inputs.logger,
            by_file=by_file,
        )

        def items() -> Iterator[pa.Table]:
            # A full refresh stages the cursor too. A later switch to append then continues from
            # the version the table holds, and not from the cursor of an earlier append.
            cursor_manager.stage(read.cursor)
            yield from read.iter_tables(with_version=appends, with_file_names=by_file)

        return SourceResponse(
            name=inputs.schema_name,
            items=items,
            primary_keys=None,
            chunk_size_bytes=CHUNK_SIZE_BYTES,
            destination_reset_required=read.reset_required,
            preserve_column_names=table.preserve_column_names,
            replace_scope=read.replace_scope,
        )

    def _find_table(
        self, store: ObjectStore, config: ConfigType, schema_name: str, logger: FilteringBoundLogger
    ) -> TableDefinition:
        """Find a table by name when its schema predates `schema_metadata`."""
        for table in self._discover(store, config, logger):
            if table.name == schema_name:
                return table
        raise ObjectStorageError(
            f"{NO_TABLE_FILES_ERROR} '{schema_name}'. The files it was discovered from may have been renamed, "
            "moved, or removed from the bucket."
        )


def _source_schema(table: TableDefinition) -> SourceSchema:
    is_files = table.kind == "files"
    return SourceSchema(
        name=table.name,
        # Delta rows have no key to merge on, so an incremental sync of a Delta table replaces rows by data file.
        supports_incremental=True,
        supports_append=True,
        incremental_fields=[
            incremental_field(FILE_MODIFIED_AT_COLUMN)
            if is_files
            else incremental_field(DELTA_VERSION_COLUMN, IncrementalFieldType.Integer)
        ],
        prefers_full_refresh=True,
        schema_metadata=table.schema_metadata(),
    )


def iter_table(
    store: ObjectStore,
    table: TableDefinition,
    logger: FilteringBoundLogger,
    selection: FileSelection = READ_ALL,
) -> Iterator[pa.Table]:
    if table.kind == "delta":
        yield from iter_delta_tables(
            store.delta_uri(table.path), store.delta_storage_options, table.name, logger=logger
        )
        return

    # Taken before listing: a file that lands during a slow listing can share a timestamp with a listed
    # file, so the append settle window has to count from before the listing started.
    listing_started_at = datetime.now(UTC)
    resolved = _resolve_files(store, table, logger)
    yield from _iter_files(store, resolved, selection.select(resolved.files, now=listing_started_at), logger)


def _resolve_files(store: ObjectStore, table: TableDefinition, logger: FilteringBoundLogger) -> TableDefinition:
    try:
        return resolve_table_files(store, table, logger=logger)
    except Exception as e:
        _raise_translated(e, store.root)


def _file_format(resolved: TableDefinition, stored: StoredObject) -> FileFormat | None:
    return resolve_file_format(stored.path, resolved.file_format)


def _iter_files(
    store: ObjectStore, resolved: TableDefinition, files: list[StoredObject], logger: FilteringBoundLogger
) -> Iterator[pa.Table]:
    for stored in files:
        file_format = _file_format(resolved, stored)
        if file_format is None:
            continue
        try:
            with store.open(stored.path) as stream:
                yield from iter_file_tables(stream, stored, file_format, resolved.csv, logger)
        except PermissionError as e:
            _raise_translated(e, store.root)


def _mirrors_files(inputs: SourceInputs) -> bool:
    """Whether an incremental read deletes the rows of deleted and rewritten files (see `ReplaceScope`)."""
    schema = (
        ExternalDataSchema.objects.filter(team_id=inputs.team_id, id=inputs.schema_id).select_related("source").first()
    )
    return schema is not None and is_schema_flag_enabled(schema, REPLACE_ROWS_BY_FILE_FLAG)
