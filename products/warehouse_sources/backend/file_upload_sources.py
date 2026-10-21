"""Turn uploaded files into file upload sources, and replace the file a source reads.

A table made from an upload keeps reading the file in place until the first sync of its source
finishes. That sync's last step points the same row at the imported copy (see
`DataWarehouseTable.adopt_into_source`), so the table keeps its id and its name. The schema's schedule
stays paused: PostHog starts each billable sync itself, once when the table is made and once for each
new file.

A table the self-managed migration moved here has a source that reads no file yet. Its schema does not
link to the table but names it in `schema_metadata` (see `SelfManagedTableRef`), and the table keeps
reading its old file in place. The next upload for the table points the source at the new file, and the
sync of that file adopts the same table row.
"""

import uuid
from typing import Any, cast, get_args

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team
from posthog.temporal.common.client import sync_connect

from products.data_warehouse.backend.facade.api import sync_external_data_job_workflow
from products.warehouse_sources.backend.ad_hoc_sync import trigger_ad_hoc_sync
from products.warehouse_sources.backend.facade.contracts import (
    FileUploadSourceError,
    UnreadableUploadError,
    UploadedFileRef,
    UploadReadSettings,
)
from products.warehouse_sources.backend.file_uploads import (
    FILE_FORMAT_TO_TABLE_FORMAT,
    HostedUpload,
    InvalidUploadError,
    UploadLocation,
    parse_hosted_upload,
)
from products.warehouse_sources.backend.models.external_data_destination import (
    ExternalDataSourceDestination,
    get_or_create_warehouse_destination,
)
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    SCHEMA_PINNED_METADATA_KEY,
    SCHEMA_SELF_MANAGED_TABLE_METADATA_KEY,
    ExternalDataSchema,
    self_managed_table_ref,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.presentation.views.external_data_source.helpers import (
    source_feature_flag_missing,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.config import CsvOptions
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.csv_types import (
    csv_column_types_from_columns,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.discovery import (
    TableDefinition,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.self_managed import (
    needs_preserved_column_names,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.file_upload.source import (
    FileUploadSource,
    UploadedFileFormat,
    read_format,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.file_upload.storage import (
    SupersededUpload,
    connection_metadata_with_superseded,
    lock_source,
    superseded_uploads,
    upload_from_job_inputs,
)
from products.warehouse_sources.backend.types import ExternalDataJobStatus, ExternalDataSourceCreatedVia

logger = structlog.get_logger(__name__)

WORKFLOW_ID_PREFIX = "file-upload"
# Kept when a new file replaces a schema's read options: they tie a migration schema to the table it adopts.
_MIGRATION_METADATA_KEYS = (SCHEMA_PINNED_METADATA_KEY, SCHEMA_SELF_MANAGED_TABLE_METADATA_KEY)


@frozen
class UploadedFile:
    """An upload in the team's own folder, and the format it is read in."""

    location: UploadLocation
    file_format: UploadedFileFormat

    @classmethod
    def from_ref(cls, team_id: int, ref: UploadedFileRef) -> "UploadedFile":
        if ref.file_format not in get_args(UploadedFileFormat):
            raise FileUploadSourceError(f"'{ref.file_format}' isn't a format a file can be uploaded in.")
        try:
            location = UploadLocation(team_id=team_id, upload_id=ref.upload_id, filename=ref.filename)
        except InvalidUploadError as e:
            raise FileUploadSourceError(str(e)) from e
        return cls(location=location, file_format=cast(UploadedFileFormat, ref.file_format))


def read_upload_in_place(team_id: int, table_name: str, upload: UploadedFile) -> UploadReadSettings:
    """Read an upload's columns, and its CSV quoting, the way the in-place table reads it."""
    probe = DataWarehouseTable(
        team_id=team_id,
        name=table_name,
        format=FILE_FORMAT_TO_TABLE_FORMAT[upload.file_format],
        url_pattern=upload.location.url_pattern,
    )
    allow_double_quotes: bool | None = None
    # An upload carries no quote preference, unlike a self-managed source where the user picks
    # one, so store a detected setting rather than leave the read to a ClickHouse default.
    if probe._is_csv_format():
        try:
            allow_double_quotes = probe.detect_csv_double_quotes_setting()
        except Exception as e:
            capture_exception(e)
        if allow_double_quotes is None:
            raise UnreadableUploadError("PostHog couldn't read the file as CSV.")
        probe.options = {"csv_allow_double_quotes": allow_double_quotes}
    try:
        columns = probe.get_columns()
    except Exception as e:
        # The raw failure is a ClickHouse error that's opaque to users, so it stays in error tracking.
        capture_exception(e)
        raise UnreadableUploadError("PostHog couldn't read the file's columns.") from e
    return UploadReadSettings(columns=columns, allow_double_quotes=allow_double_quotes)


def file_upload_source() -> FileUploadSource:
    return FileUploadSource()


def file_upload_sources_enabled(team: Team) -> bool:
    return not source_feature_flag_missing(file_upload_source(), team)


def upload_job_inputs(upload: UploadedFile, schema_name: str) -> dict[str, str]:
    return {
        "upload_id": upload.location.upload_id,
        "filename": upload.location.filename,
        "file_format": upload.file_format,
        "schema_name": schema_name,
    }


def pending_upload_job_inputs(file_format: UploadedFileFormat, schema_name: str) -> dict[str, str]:
    """Inputs of a source that reads no file yet. A sync of it fails until an upload replaces them."""
    return {"upload_id": "", "filename": "", "file_format": file_format, "schema_name": schema_name}


def upload_schema_metadata(
    schema_name: str,
    filename: str,
    file_format: UploadedFileFormat,
    read_settings: UploadReadSettings,
    preserve_column_names: bool,
) -> dict[str, Any]:
    """The read options the sync applies to the file: the column types and quoting the in-place read
    used, and whether to keep the column names as the file writes them."""
    read = read_format(file_format)
    return TableDefinition(
        name=schema_name,
        kind="files",
        path=filename,
        scope="file",
        file_format=read,
        csv=CsvOptions(
            has_header=True,
            allow_double_quotes=read_settings.allow_double_quotes is not False,
            column_types=csv_column_types_from_columns(read_settings.columns) if read == "csv" else (),
        ),
        pattern=None,
        source_format=read,
        preserve_column_names=preserve_column_names,
    ).schema_metadata()


def _source_created_via(table: DataWarehouseTable) -> str | None:
    return table.created_via if table.created_via in ExternalDataSourceCreatedVia.values else None


def create_source_for_upload(
    table: DataWarehouseTable,
    job_inputs: dict[str, Any],
    connection_metadata: dict[str, Any] | None = None,
) -> ExternalDataSource:
    source = ExternalDataSource.objects.create(
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        team_id=table.team_id,
        status=ExternalDataSource.Status.RUNNING,
        source_type=file_upload_source().source_type,
        api_version=file_upload_source().default_version,
        job_inputs=job_inputs,
        description=f"Uploaded file for {table.name}"[:400],
        access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
        created_by=table.created_by,
        created_via=_source_created_via(table),
        connection_metadata=connection_metadata or {},
    )
    ExternalDataSourceDestination.objects.for_team(table.team_id).create(
        team_id=table.team_id, source_id=source.pk, destination=get_or_create_warehouse_destination(table.team_id)
    )
    return source


def create_file_upload_source(
    table: DataWarehouseTable, upload: UploadedFile, read_settings: UploadReadSettings
) -> ExternalDataSchema:
    """Create the source that imports a saved table made from an upload, then start the first sync.

    The table reads the file in place until that sync finishes, so a sync that fails to start leaves a
    working table. The schema's sync action can start it again.
    """
    preserve = needs_preserved_column_names(read_settings.columns.keys())
    with transaction.atomic():
        source = create_source_for_upload(table, upload_job_inputs(upload, table.name))
        schema = ExternalDataSchema.objects.create(
            name=table.name,
            team_id=table.team_id,
            source=source,
            table=table,
            should_sync=False,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            sync_type_config={
                "schema_metadata": upload_schema_metadata(
                    table.name, upload.location.filename, upload.file_format, read_settings, preserve
                )
            },
        )
    try:
        start_file_upload_sync(schema)
    except FileUploadSourceError:
        logger.warning("Could not start the first sync of a file upload source", schema_id=str(schema.id))
    return schema


def start_file_upload_sync(schema: ExternalDataSchema) -> str:
    """Start one billable sync, with the schedule created paused so it never starts one of its own."""
    try:
        sync_external_data_job_workflow(schema, create=True, should_sync=False, trigger_immediately=False)
        trigger = trigger_ad_hoc_sync(
            sync_connect(), schema, billable=True, reset_pipeline=False, workflow_id_prefix=WORKFLOW_ID_PREFIX
        )
    except Exception as e:
        capture_exception(e)
        raise FileUploadSourceError("PostHog couldn't start the sync of the file. Try again in a few minutes.") from e
    return trigger.workflow_id


def find_file_upload_schema(table: DataWarehouseTable) -> ExternalDataSchema | None:
    """The live file upload schema that links to the table, if one does."""
    return (
        ExternalDataSchema.objects.filter(
            team_id=table.team_id,
            table_id=table.pk,
            deleted=False,
            source__deleted=False,
            source__source_type=file_upload_source().source_type,
        )
        .select_related("source")
        .order_by("created_at")
        .first()
    )


def find_migration_upload_schema(table: DataWarehouseTable) -> ExternalDataSchema | None:
    """The live file upload schema the migration made for the table, while its sync would still adopt it.

    The schema does not link to the table yet. It names the table and the file the table read, and a
    table that reads another file now is no longer the one the schema replaces.
    """
    if table.external_data_source_id is not None:
        return None
    schemas = (
        ExternalDataSchema.objects.filter(
            team_id=table.team_id,
            table__isnull=True,
            deleted=False,
            source__deleted=False,
            source__source_type=file_upload_source().source_type,
            sync_type_config__schema_metadata__self_managed_table__table_id=str(table.pk),
        )
        .select_related("source")
        .order_by("created_at")
    )
    for schema in schemas:
        ref = self_managed_table_ref(schema)
        if ref is not None and (ref.url_pattern, ref.format) == (table.url_pattern, table.format):
            return schema
    return None


def find_replaceable_upload_schema(table: DataWarehouseTable) -> ExternalDataSchema | None:
    """The file upload schema a new file for the table goes to."""
    return find_file_upload_schema(table) or find_migration_upload_schema(table)


def _file_read_in_place(schema: ExternalDataSchema) -> HostedUpload | None:
    """The uploaded file the table of a migration schema still reads, before the schema's sync adopts it."""
    ref = self_managed_table_ref(schema)
    if schema.table_id is not None or ref is None:
        return None
    return parse_hosted_upload(schema.team_id, ref.url_pattern)


def replace_file_upload(schema: ExternalDataSchema, upload: UploadedFile, read_settings: UploadReadSettings) -> str:
    """Point the schema's source at a new upload and start a billable full refresh of it.

    The table keeps its row and its name. The old file is recorded as superseded and is deleted
    once a sync that started after this call completes (see `FileUploadSource.cleanup_after_sync`).
    For a migrated table that is the file it reads in place until that sync adopts it.
    """
    with transaction.atomic():
        source = lock_source(str(schema.source_id), schema.team_id)
        if source is None:
            raise FileUploadSourceError("This table's source was deleted.")
        # Checked under the source's lock, so two replacements of one table can't both pass it.
        latest_job = (
            ExternalDataJob.objects.filter(team_id=schema.team_id, schema_id=schema.id).order_by("-created_at").first()
        )
        if latest_job is not None and latest_job.status == ExternalDataJobStatus.RUNNING:
            raise FileUploadSourceError("A sync of this table is running. Replace the file once it finishes.")
        try:
            current: HostedUpload | None = upload_from_job_inputs(source.team_id, source.job_inputs)
        except InvalidUploadError:
            current = None
        source.job_inputs = {**(source.job_inputs or {}), **upload_job_inputs(upload, schema.name)}
        now = timezone.now()
        recorded = {entry.upload for entry in superseded_uploads(source)}
        replaced: list[HostedUpload] = [old for old in (current, _file_read_in_place(schema)) if old is not None]
        for old in dict.fromkeys(replaced):
            if old != upload.location and old not in recorded:
                source.connection_metadata = connection_metadata_with_superseded(
                    source, SupersededUpload(upload=old, superseded_at=now)
                )
        source.save(update_fields=["job_inputs", "connection_metadata", "updated_at"])

        previous = TableDefinition.from_schema_metadata(schema.name, schema.schema_metadata)
        # Keep the column naming the table already has, so queries written against it keep working.
        preserve = (
            previous.preserve_column_names
            if previous is not None
            else needs_preserved_column_names(read_settings.columns.keys())
        )
        metadata = upload_schema_metadata(
            schema.name, upload.location.filename, upload.file_format, read_settings, preserve
        )

        def replace_metadata(config: dict[str, Any]) -> None:
            stored = config.get("schema_metadata")
            stored = stored if isinstance(stored, dict) else {}
            config["schema_metadata"] = {
                **metadata,
                **{key: stored[key] for key in _MIGRATION_METADATA_KEYS if key in stored},
            }

        schema.sync_type_config = update_sync_type_config_keys(schema.id, schema.team_id, mutate=replace_metadata)
        # A new file replaces the table's rows, so the sync must be a full refresh, never an append.
        if schema.sync_type != ExternalDataSchema.SyncType.FULL_REFRESH:
            schema.sync_type = ExternalDataSchema.SyncType.FULL_REFRESH
            ExternalDataSchema.objects.filter(pk=schema.pk, team_id=schema.team_id).update(
                sync_type=schema.sync_type, updated_at=now
            )
    schema.source = source
    return start_file_upload_sync(schema)
