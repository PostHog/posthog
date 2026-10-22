from collections.abc import Iterator
from typing import Any, Literal, Optional, cast

from django.conf import settings
from django.db import transaction

import pyarrow as pa
from structlog.types import FilteringBoundLogger

from products.data_warehouse.backend.facade.api import get_s3_client
from products.warehouse_sources.backend.facade.codebase_detection import NOT_DETECTABLE
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
)
from products.warehouse_sources.backend.file_uploads import InvalidUploadError, UploadLocation
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common import config
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.config import (
    CsvOptions,
    FileFormat,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.csv_types import (
    csv_column_types_from_metadata,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.errors import (
    FILE_PARSE_ERROR,
    INVALID_CONFIG_ERROR,
    NO_TABLE_FILES_ERROR,
    ObjectStorageError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.fields import FEATURE_FLAG
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.filesystem import ObjectStore
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.formats import (
    iter_file_tables,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.settings import (
    CHUNK_SIZE_BYTES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.file_upload.storage import (
    delete_source_uploads,
    release_superseded_uploads,
    superseded_uploads,
    upload_from_job_inputs,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

UploadedFileFormat = Literal["csv", "json", "parquet"]

# JSON uploads are read one object per line, the same as the in-place table read them.
_READ_FORMATS: dict[UploadedFileFormat, FileFormat] = {"csv": "csv", "json": "jsonl", "parquet": "parquet"}

# Written by PostHog when it creates the source or replaces its file. The update endpoint pins them,
# so no request can point a source at a different object.
SERVER_MANAGED_FIELDS = ("upload_id", "filename", "file_format", "schema_name")


@config.config
class FileUploadInputs(config.Config):
    file_format: UploadedFileFormat
    # The source's one schema. Discovery returns it, so a refresh never adds a second table.
    schema_name: str
    # Empty until the first upload of a source the migration made, so an update of such a source still
    # validates. A sync of it fails, because an empty id names no upload.
    upload_id: str = ""
    filename: str = ""


def upload_location(inputs: FileUploadInputs, team_id: int) -> UploadLocation:
    """Where the source's file is. The team is the source's own, so the path stays in its folder."""
    try:
        return UploadLocation(team_id=team_id, upload_id=inputs.upload_id, filename=inputs.filename)
    except InvalidUploadError as e:
        raise ObjectStorageError(f"{INVALID_CONFIG_ERROR}: {e}") from e


def read_format(file_format: str) -> FileFormat:
    read = _READ_FORMATS.get(cast(UploadedFileFormat, file_format))
    if read is None:
        raise ObjectStorageError(f"{INVALID_CONFIG_ERROR}: '{file_format}' isn't a format a file can be uploaded in.")
    return read


def open_upload_store(location: UploadLocation) -> ObjectStore:
    """A store rooted at the upload's own folder, read with PostHog's storage access.

    Only this source uses PostHog's access, and only for a path built from the team id and a checked
    upload id. Customer sources go through `ObjectStorageSource.open_store`, which refuses PostHog's
    bucket.
    """
    return ObjectStore(
        fs=get_s3_client(skip_instance_cache=True),
        root=f"{settings.DATAWAREHOUSE_BUCKET}/{location.folder_key}",
        delta_uri_prefix="s3://",
        delta_storage_options={},
    )


def iter_upload_tables(
    store: ObjectStore,
    filename: str,
    file_format: FileFormat,
    csv: CsvOptions,
    logger: FilteringBoundLogger | None = None,
) -> Iterator[pa.Table]:
    matches = [stored for stored in store.list_objects(filename, 1) if stored.path == filename]
    if not matches:
        raise ObjectStorageError(f"{NO_TABLE_FILES_ERROR} '{filename}'. The uploaded file is no longer stored.")
    with store.open(filename) as stream:
        yield from iter_file_tables(stream, matches[0], file_format, csv, logger)


@SourceRegistry.register
class FileUploadSource(SimpleSource[FileUploadInputs]):
    """Imports one file a user uploaded to PostHog into a managed table.

    PostHog creates the source when a table is made from an upload, and starts each sync itself: once
    at creation, and once each time the file is replaced. The schema's schedule stays paused.
    """

    requires_team_feature_flag = FEATURE_FLAG
    syncs_on_demand = True
    listed_in_catalog = False
    # A file someone uploads leaves no trace in a codebase.
    codebase_detection = NOT_DETECTABLE

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FILEUPLOAD

    @property
    def _config_class(self) -> type[FileUploadInputs]:
        # Every input is server-managed, so the setup form declares no fields to generate a config from.
        return FileUploadInputs

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FILEUPLOAD,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            label="File upload",
            caption="Upload a CSV, JSON, or Parquet file to query it in the PostHog data warehouse.",
            iconPath="/static/services/file-upload.svg",
            releaseStatus=ReleaseStatus.ALPHA,
            featureFlag=FEATURE_FLAG,
            fields=[],
        )

    def server_managed_job_input_fields(
        self, incoming_job_inputs: dict[str, Any], existing_job_inputs: dict[str, Any]
    ) -> list[str]:
        return list(SERVER_MANAGED_FIELDS)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            INVALID_CONFIG_ERROR: None,
            NO_TABLE_FILES_ERROR: "The uploaded file is no longer stored. Upload the file again to replace it.",
            FILE_PARSE_ERROR: None,
        }

    def validate_credentials(
        self,
        config: FileUploadInputs,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            location = upload_location(config, team_id)
            found = open_upload_store(location).list_objects(location.filename, 1)
        except ObjectStorageError as e:
            return False, str(e)
        if not any(stored.path == location.filename for stored in found):
            return False, "The uploaded file wasn't found. Upload the file again."
        return True, None

    def get_schemas(
        self,
        config: FileUploadInputs,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        if names is not None and config.schema_name not in names:
            return []
        return [
            SourceSchema(
                name=config.schema_name,
                supports_incremental=False,
                supports_append=False,
                prefers_full_refresh=True,
                should_sync_default=False,
            )
        ]

    def source_for_pipeline(self, config: FileUploadInputs, inputs: SourceInputs) -> SourceResponse:
        location = upload_location(config, inputs.team_id)
        file_format = read_format(config.file_format)
        # The schema keeps the read options PostHog chose for the file (CSV column types, raw column
        # names). Where the file is comes from the source's inputs, never from the schema.
        metadata = inputs.schema_metadata or {}
        csv_metadata = metadata.get("csv")
        csv_metadata = csv_metadata if isinstance(csv_metadata, dict) else {}
        csv = CsvOptions(
            has_header=True,
            allow_double_quotes=csv_metadata.get("allow_double_quotes") is not False,
            column_types=csv_column_types_from_metadata(csv_metadata.get("column_types"))
            if file_format == "csv"
            else (),
        )

        def items() -> Iterator[pa.Table]:
            yield from iter_upload_tables(
                open_upload_store(location), location.filename, file_format, csv, inputs.logger
            )

        return SourceResponse(
            name=inputs.schema_name,
            items=items,
            primary_keys=None,
            chunk_size_bytes=CHUNK_SIZE_BYTES,
            preserve_column_names=metadata.get("preserve_column_names") is True,
        )

    def manual_sync_refusal(self, source_model: ExternalDataSource) -> str | None:
        # A source the self-managed migration made reads no file until the next upload for its table.
        try:
            upload_from_job_inputs(source_model.team_id, source_model.job_inputs)
        except InvalidUploadError:
            return "This table syncs when you upload a new file for it. Upload the file to import it."
        return None

    def has_cleanup_after_sync(self, source_model: ExternalDataSource) -> bool:
        return bool(superseded_uploads(source_model))

    def cleanup_after_sync(self, source_model: ExternalDataSource, job: ExternalDataJob) -> None:
        release_superseded_uploads(str(source_model.pk), source_model.team_id, job.created_at)

    def on_source_deleted(self, source_model: ExternalDataSource) -> None:
        # After the commit, so a delete that rolls back never leaves a live source without its file.
        transaction.on_commit(lambda: delete_source_uploads(source_model))
