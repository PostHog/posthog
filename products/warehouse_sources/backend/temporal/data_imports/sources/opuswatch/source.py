import re
from datetime import datetime
from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.opuswatch import (
    OPUSWatchSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opuswatch.opuswatch import (
    OPUSWatchResumeConfig,
    opuswatch_source,
    validate_credentials as validate_opuswatch_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opuswatch.settings import (
    DEFAULT_START_DATE,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    OPUSWATCH_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_START_DATE_RE = re.compile(r"^\d{8}$")


@SourceRegistry.register
class OPUSWatchSource(ResumableSource[OPUSWatchSourceConfig, OPUSWatchResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # OPUS Solutions publishes no versioned API reference; the ext API base URL is the
    # closest stable pointer to the API surface.
    api_docs_url = "https://api.opuswatch.nl/ext/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OPUSWATCH

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Your OPUSWatch API key is invalid or has been revoked. Please check the key and reconnect.",
            "403 Client Error: Forbidden for url": "Your OPUSWatch API key does not have permission to access this data. Please check the key and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.opuswatch.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: OPUSWatchSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: OPUSWatchSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        start_date = (config.start_date or "").strip()
        if start_date:
            if not _START_DATE_RE.match(start_date):
                return False, "Start date must be in YYYYMMDD format, e.g. 20250101"
            try:
                datetime.strptime(start_date, "%Y%m%d")
            except ValueError:
                return False, "Start date is not a valid date"

        if validate_opuswatch_credentials(config.api_key):
            return True, None

        return False, "Invalid OPUSWatch API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OPUSWatchResumeConfig]:
        return ResumableSourceManager[OPUSWatchResumeConfig](inputs, OPUSWatchResumeConfig)

    def source_for_pipeline(
        self,
        config: OPUSWatchSourceConfig,
        resumable_source_manager: ResumableSourceManager[OPUSWatchResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        endpoint_config = OPUSWATCH_ENDPOINTS[inputs.schema_name]
        resource = opuswatch_source(
            api_key=config.api_key,
            start_date=config.start_date,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
        has_partitioning = endpoint_config.partition_key is not None
        return SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=[endpoint_config.primary_key],
            partition_count=1 if has_partitioning else None,
            partition_size=1 if has_partitioning else None,
            partition_mode="datetime" if has_partitioning else None,
            partition_format="month" if has_partitioning else None,
            partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
            # The API documents no ordering for the offset-paginated transactional
            # endpoints, so treat rows as unordered: "desc" defers the incremental
            # watermark to job completion instead of checkpointing it per batch.
            sort_mode="desc" if endpoint_config.supports_date_window else "asc",
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OPUS_WATCH,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="OPUSWatch",
            caption="Import master data, work registrations, and productivity sessions from OPUSWatch by OPUS Solutions.",
            docsUrl="https://posthog.com/docs/cdp/sources/opuswatch",
            iconPath="/static/services/opuswatch.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        caption="The API key for the OPUSWatch external API, issued by OPUS Solutions.",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder=DEFAULT_START_DATE,
                        caption=f"Sync registrations and sessions created from this date, in YYYYMMDD format. Defaults to {DEFAULT_START_DATE}.",
                        secret=False,
                    ),
                ],
            ),
        )
