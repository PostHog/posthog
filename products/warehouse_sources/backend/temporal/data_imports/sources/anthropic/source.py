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
    ANTHROPIC_RETRYABLE_ERROR_PREFIX,
    AnthropicResumeConfig,
    anthropic_source,
    validate_credentials as validate_anthropic_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.settings import (
    ANTHROPIC_ENDPOINTS,
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
    supported_versions = ("2023-06-01",)
    default_version = "2023-06-01"
    api_docs_url = "https://platform.claude.com/docs/en/api/versioning"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ANTHROPIC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ANTHROPIC,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Anthropic",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Anthropic Admin API key to pull your organization's Claude usage, cost, and admin data into the PostHog Data warehouse.

Create an Admin API key (prefixed `sk-ant-admin...`) in your [Anthropic Console](https://console.anthropic.com/settings/admin-keys). Only organization admins can create one, and the Admin API is not available for individual accounts.""",
            iconPath="/static/services/anthropic.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/anthropic",
            keywords=["llm", "claude", "ai usage", "cost"],
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

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.anthropic.com": "Your Anthropic Admin API key is invalid or has been revoked. Create a new Admin API key in the Anthropic Console, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.anthropic.com": "Your Anthropic API key does not have organization admin access. Use an Admin API key (prefixed sk-ant-admin) created by an organization admin, then reconnect.",
        }

    def get_expected_retryable_errors(self) -> dict[str, str | None]:
        # The rate-limited report endpoints (usage_report/cost_report) can trip Anthropic's 429 limit
        # for longer than `_fetch_page`'s in-process backoff rides out, exhausting its retries and
        # re-raising this. Temporal retries the activity, so it's an expected transient condition, not
        # an error worth surfacing in error tracking.
        return {ANTHROPIC_RETRYABLE_ERROR_PREFIX: None}

    def get_schemas(
        self,
        config: AnthropicSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = ANTHROPIC_ENDPOINTS[endpoint]
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
