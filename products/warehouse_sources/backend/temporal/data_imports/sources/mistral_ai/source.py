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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MistralAISourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mistral_ai.mistral_ai import (
    MistralAIResumeConfig,
    mistral_ai_source,
    validate_credentials as validate_mistral_ai_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mistral_ai.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    MISTRAL_AI_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MistralAISource(ResumableSource[MistralAISourceConfig, MistralAIResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MISTRALAI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MISTRAL_AI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Mistral AI",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Mistral AI API key to sync your Mistral AI platform data into the PostHog Data warehouse.

You can create an API key in [La Plateforme](https://console.mistral.ai/api-keys).""",
            iconPath="/static/services/mistral_ai.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/mistral-ai",
            keywords=["llm", "ai", "fine-tuning", "mistral"],
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.mistral_ai.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch_page` calls raise_for_status().
            # Retrying can never satisfy a credential problem, so permanently fail the sync. Match the
            # stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.mistral.ai": "Your Mistral AI API key is invalid or has been revoked. Create a new key in La Plateforme, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.mistral.ai": "Your Mistral AI API key is missing the permissions needed to sync this data. Check the key's permissions in La Plateforme, then reconnect.",
        }

    def get_schemas(
        self,
        config: MistralAISourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=MISTRAL_AI_ENDPOINTS[endpoint].supports_incremental,
                supports_append=MISTRAL_AI_ENDPOINTS[endpoint].supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=MISTRAL_AI_ENDPOINTS[endpoint].should_sync_default,
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: MistralAISourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_mistral_ai_credentials(config.api_key):
            return True, None

        return False, "Invalid Mistral AI API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MistralAIResumeConfig]:
        return ResumableSourceManager[MistralAIResumeConfig](inputs, MistralAIResumeConfig)

    def source_for_pipeline(
        self,
        config: MistralAISourceConfig,
        resumable_source_manager: ResumableSourceManager[MistralAIResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return mistral_ai_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
