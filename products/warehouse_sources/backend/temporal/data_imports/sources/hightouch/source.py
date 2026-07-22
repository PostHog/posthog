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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hightouch import (
    HightouchSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hightouch.hightouch import (
    HightouchResumeConfig,
    hightouch_source,
    validate_credentials as validate_hightouch_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hightouch.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SYNC_RUNS_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HightouchSource(ResumableSource[HightouchSourceConfig, HightouchResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://hightouch.com/docs/api-reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HIGHTOUCH

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Hightouch API key is invalid or was revoked. Create a new key in your Hightouch workspace settings and reconnect.",
            "403 Client Error": "Your Hightouch API key is missing the required permissions. Check the key in your Hightouch workspace settings and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.hightouch.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: HightouchSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # sync_runs is merge-only: runs still in progress mutate (status, finishedAt, row
        # counts) and the trailing lookback window re-reads them, so append mode would
        # duplicate rows instead of upserting.
        schemas = build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=("sync_runs",))
        for schema in schemas:
            if schema.name == "sync_runs":
                schema.default_incremental_lookback_seconds = SYNC_RUNS_LOOKBACK_SECONDS
        return schemas

    def validate_credentials(
        self,
        config: HightouchSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        # Hightouch API keys are workspace-scoped with no per-resource permissions, so a
        # single probe validates access to every endpoint.
        return validate_hightouch_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HightouchResumeConfig]:
        return ResumableSourceManager[HightouchResumeConfig](inputs, HightouchResumeConfig)

    def source_for_pipeline(
        self,
        config: HightouchSourceConfig,
        resumable_source_manager: ResumableSourceManager[HightouchResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return hightouch_source(
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
            name=SchemaExternalDataSourceType.HIGHTOUCH,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Hightouch",
            caption="""Enter a Hightouch API key to sync your syncs, sync runs, models, sources, and destinations.

You can create an API key in Hightouch under **Settings → API keys**. Only workspace admins can create API keys, and the key is shown once at creation.
""",
            keywords=["reverse etl", "data activation"],
            docsUrl="https://posthog.com/docs/cdp/sources/hightouch",
            iconPath="/static/services/hightouch.png",
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
