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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OpenAISourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.openai.openai import (
    OpenAIResumeConfig,
    openai_source,
    validate_credentials as validate_openai_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openai.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    OPENAI_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OpenAISource(ResumableSource[OpenAISourceConfig, OpenAIResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://platform.openai.com/docs/api-reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OPENAI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OPEN_AI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="OpenAI",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your OpenAI Admin API key to pull your organization's API usage, cost, and admin data into the PostHog Data warehouse.

Create an Admin API key (prefixed `sk-admin...`) in your [OpenAI organization settings](https://platform.openai.com/settings/organization/admin-keys). Only organization owners can create one; a regular project API key cannot read organization usage or costs.""",
            iconPath="/static/services/openai.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/openai",
            keywords=["llm", "gpt", "chatgpt", "ai usage", "cost"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Admin API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sk-admin...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.openai.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.openai.com": "Your OpenAI Admin API key is invalid or has been revoked. Create a new Admin API key in your OpenAI organization settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.openai.com": "Your OpenAI API key does not have organization admin access. Use an Admin API key (prefixed sk-admin) created by an organization owner, then reconnect.",
        }

    def get_schemas(
        self,
        config: OpenAISourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = OPENAI_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_append,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                default_incremental_lookback_seconds=endpoint_config.default_incremental_lookback_seconds,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: OpenAISourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_openai_credentials(config.api_key):
            return True, None

        return False, "Invalid OpenAI Admin API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OpenAIResumeConfig]:
        return ResumableSourceManager[OpenAIResumeConfig](inputs, OpenAIResumeConfig)

    def source_for_pipeline(
        self,
        config: OpenAISourceConfig,
        resumable_source_manager: ResumableSourceManager[OpenAIResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return openai_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
