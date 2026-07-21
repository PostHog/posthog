from typing import Any, Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.data_warehouse.backend.facade.api import get_s3_client
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.file_upload.file_upload import (
    FILE_TOO_LARGE_ERROR,
    file_upload_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.file_upload.settings import (
    SUPPORTED_FILE_FORMATS,
    build_file_upload_s3_path,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fileupload import (
    FileUploadSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FileUploadSource(SimpleSource[FileUploadSourceConfig]):
    """A user-uploaded flat file (CSV, JSON, or Parquet) stored in PostHog's own object storage.

    The wizard uploads the file to the data warehouse bucket first, then creates the source pointing
    at the resulting object. Unlike self-managed S3/GCS sources, PostHog owns the bucket, so no
    customer credentials are involved — the file's location is server-owned and pinned on update."""

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FILEUPLOAD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FILE_UPLOAD,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            label="File upload",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["csv", "json", "parquet", "file", "upload", "flat file", "spreadsheet"],
            caption="Upload a CSV, JSON, or Parquet file to import it into the PostHog Data warehouse as a table.",
            iconPath="/static/services/file-upload.svg",
            # The wizard renders a bespoke upload form for this source, so these job-input fields are
            # populated by that form rather than the generic source form. `upload_id` and `filename`
            # are server-owned (pinned on update — see `server_managed_job_input_fields`).
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="table_name",
                        label="Table name",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my_table",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="file_format",
                        label="File format",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="csv",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="upload_id",
                        label="Upload id",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="filename",
                        label="Filename",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # A file that decodes past the size cap will never succeed on retry — fail the sync instead.
        return {
            FILE_TOO_LARGE_ERROR: (
                "The uploaded file is too large to import once decompressed. Upload a smaller file, or "
                "connect the bucket it lives in as a self-managed source instead."
            ),
        }

    def server_managed_job_input_fields(
        self, incoming_job_inputs: dict[str, Any], existing_job_inputs: dict[str, Any]
    ) -> list[str]:
        # The uploaded object's location is owned by the upload endpoint, never the client. Pinning
        # both fields on update stops an org member repointing an existing source at a different key.
        return ["upload_id", "filename"]

    def get_schemas(
        self,
        config: FileUploadSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # One uploaded file = one table, named by the user. Full refresh only: a flat file has no
        # server-side change filter and no reliable unique key.
        schemas = [
            SourceSchema(
                name=config.table_name,
                supports_incremental=False,
                supports_append=False,
            )
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: FileUploadSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if config.file_format not in SUPPORTED_FILE_FORMATS:
            return False, f"Unsupported file format '{config.file_format}'."

        path = build_file_upload_s3_path(team_id, config.upload_id, config.filename)
        try:
            if not get_s3_client().exists(path):
                return False, "Uploaded file not found. Please upload the file again."
        except Exception:
            return False, "Could not verify the uploaded file. Please try uploading it again."
        return True, None

    def source_for_pipeline(self, config: FileUploadSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return file_upload_source(
            team_id=inputs.team_id,
            upload_id=config.upload_id,
            filename=config.filename,
            file_format=config.file_format,
            inputs=inputs,
        )
