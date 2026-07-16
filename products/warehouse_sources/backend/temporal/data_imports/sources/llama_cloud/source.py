from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LlamaCloudSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.llama_cloud.llama_cloud import (
    LlamaCloudResumeConfig,
    llama_cloud_source,
    validate_credentials as validate_llama_cloud_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.llama_cloud.settings import (
    DEFAULT_LLAMA_CLOUD_REGION,
    ENDPOINTS,
    LLAMA_CLOUD_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LlamaCloudSource(ResumableSource[LlamaCloudSourceConfig, LlamaCloudResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LLAMACLOUD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LLAMA_CLOUD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="LlamaCloud",
            docsUrl="https://posthog.com/docs/cdp/sources/llama-cloud",
            iconPath="/static/services/llama_cloud.svg",
            keywords=["llamaindex", "llamaparse", "document parsing", "rag"],
            caption="""Enter a LlamaCloud API key to sync your parsing, extraction, and classification jobs, pipelines, projects, files, and usage metrics.

You can create an API key in [LlamaCloud](https://cloud.llamaindex.ai) under **Settings → API Keys**. API keys are project-scoped and region-specific, so pick the region your key was created in.
""",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="llx-...",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue=DEFAULT_LLAMA_CLOUD_REGION,
                        options=[
                            SourceFieldSelectConfigOption(label="North America (api.cloud.llamaindex.ai)", value="na"),
                            SourceFieldSelectConfigOption(label="Europe (api.cloud.eu.llamaindex.ai)", value="eu"),
                        ],
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Both regional hosts share the https://api.cloud. prefix, so one key per status
        # covers NA and EU without matching unrelated hosts.
        return {
            "401 Client Error: Unauthorized for url: https://api.cloud.": "Your LlamaCloud API key is invalid, revoked, or from a different region. Create a new API key in LlamaCloud, check the region, and reconnect.",
            "403 Client Error: Forbidden for url: https://api.cloud.": "Your LlamaCloud API key does not have access to this data. Check the key's project in LlamaCloud and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.llama_cloud.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: LlamaCloudSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas: list[SourceSchema] = []
        for endpoint in ENDPOINTS:
            if names and endpoint not in names:
                continue

            endpoint_config = LLAMA_CLOUD_ENDPOINTS[endpoint]
            supports_incremental = endpoint_config.incremental_param is not None
            schemas.append(
                SourceSchema(
                    name=endpoint,
                    supports_incremental=supports_incremental,
                    supports_append=supports_incremental,
                    incremental_fields=endpoint_config.incremental_fields,
                    description=endpoint_config.description,
                    default_incremental_lookback_seconds=endpoint_config.default_incremental_lookback_seconds,
                )
            )
        return schemas

    def validate_credentials(
        self, config: LlamaCloudSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_llama_cloud_credentials(api_key=config.api_key, region=config.region)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LlamaCloudResumeConfig]:
        return ResumableSourceManager[LlamaCloudResumeConfig](inputs, LlamaCloudResumeConfig)

    def source_for_pipeline(
        self,
        config: LlamaCloudSourceConfig,
        resumable_source_manager: ResumableSourceManager[LlamaCloudResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return llama_cloud_source(
            api_key=config.api_key,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
