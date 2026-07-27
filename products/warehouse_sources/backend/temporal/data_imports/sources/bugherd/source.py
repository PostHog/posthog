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
from products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.bugherd import (
    BugherdResumeConfig,
    bugherd_source,
    validate_credentials as validate_bugherd_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bugherd import (
    BugherdSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BugherdSource(ResumableSource[BugherdSourceConfig, BugherdResumeConfig]):
    # `get_schemas` iterates a static endpoint catalog with no I/O -- safe for public docs.
    lists_tables_without_credentials = True
    api_docs_url = "https://docs.bugherd.com/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BUGHERD

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your BugHerd API key is invalid or has been revoked. Generate a new key under Settings > General Settings and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: BugherdSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: BugherdSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_bugherd_credentials(config.api_key, schema_name=schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BugherdResumeConfig]:
        return ResumableSourceManager[BugherdResumeConfig](inputs, BugherdResumeConfig)

    def source_for_pipeline(
        self,
        config: BugherdSourceConfig,
        resumable_source_manager: ResumableSourceManager[BugherdResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return bugherd_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BUGHERD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="BugHerd",
            caption="""Enter your BugHerd API key to sync your organization, projects, tasks, and users into the PostHog Data warehouse.

Find your API key in BugHerd under **Settings > General Settings** (organization owner/admin access is required).""",
            docsUrl="https://posthog.com/docs/cdp/sources/bugherd",
            iconPath="/static/services/bugherd.png",
            keywords=["bug tracking", "qa"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
