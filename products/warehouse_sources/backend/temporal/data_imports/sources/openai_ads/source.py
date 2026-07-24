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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.openaiads import (
    OpenAIAdsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openai_ads.openai_ads import (
    OpenAIAdsResumeConfig,
    openai_ads_source,
    validate_credentials as validate_openai_ads_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openai_ads.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    OPENAI_ADS_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OpenAIAdsSource(ResumableSource[OpenAIAdsSourceConfig, OpenAIAdsResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://developers.openai.com/ads/api-overview"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OPENAIADS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OPEN_AI_ADS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="OpenAI Ads",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your OpenAI Ads API key to pull your campaigns, ad groups, ads, and performance insights into the PostHog Data warehouse.

Create an API key in the Settings tab of [OpenAI Ads Manager](https://ads.openai.com). Each key is scoped to a single ad account — to import more than one ad account, connect one source per account.""",
            iconPath="/static/services/openai_ads.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/openai-ads",
            keywords=["chatgpt", "chatgpt ads", "openai advertising"],
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
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.openai_ads.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.ads.openai.com": "Your OpenAI Ads API key is invalid or has been revoked. Create a new API key in the Settings tab of OpenAI Ads Manager, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.ads.openai.com": "Your OpenAI Ads API key does not have access to this ad account. Create a key for this ad account in the Settings tab of OpenAI Ads Manager, then reconnect.",
        }

    def get_schemas(
        self,
        config: OpenAIAdsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = OPENAI_ADS_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                # Insights buckets get restated as reporting catches up, so append would
                # materialize duplicates; entity lists are full refresh only.
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                default_incremental_lookback_seconds=endpoint_config.default_incremental_lookback_seconds,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: OpenAIAdsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_openai_ads_credentials(config.api_key):
            return True, None

        return False, "Invalid OpenAI Ads API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OpenAIAdsResumeConfig]:
        return ResumableSourceManager[OpenAIAdsResumeConfig](inputs, OpenAIAdsResumeConfig)

    def source_for_pipeline(
        self,
        config: OpenAIAdsSourceConfig,
        resumable_source_manager: ResumableSourceManager[OpenAIAdsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return openai_ads_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
