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
from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.anthropic import (
    AnthropicResumeConfig,
    anthropic_source,
    validate_credentials as validate_anthropic_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AnthropicSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AnthropicSource(ResumableSource[AnthropicSourceConfig, AnthropicResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ANTHROPIC

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.anthropic.com": "Anthropic authentication failed. Please check that your Admin API key (sk-ant-admin...) is valid and has not been revoked.",
            "403 Client Error: Forbidden for url: https://api.anthropic.com": "Anthropic denied access. Please check that you are using an Admin API key (sk-ant-admin...), not a regular API key.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ANTHROPIC,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Anthropic",
            caption="""Enter your Anthropic Admin API key to pull your organization's Claude API usage, costs, members, workspaces, and API keys into the PostHog Data warehouse.

You need an **Admin API key** (starts with `sk-ant-admin...`), which only organization admins can create in the [Anthropic Console](https://console.anthropic.com/settings/admin-keys). Regular API keys (`sk-ant-api...`) do not work. The Admin API is not available for individual (non-organization) accounts.""",
            iconPath="/static/services/anthropic.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/anthropic",
            keywords=["llm", "claude", "ai usage", "cost"],
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Admin API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sk-ant-admin...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AnthropicSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: AnthropicSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_anthropic_credentials(config.api_key):
            return True, None

        return False, "Invalid Anthropic Admin API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AnthropicResumeConfig]:
        return ResumableSourceManager[AnthropicResumeConfig](inputs, AnthropicResumeConfig)

    def source_for_pipeline(
        self,
        config: AnthropicSourceConfig,
        resumable_source_manager: ResumableSourceManager[AnthropicResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return anthropic_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
