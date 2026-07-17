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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LangSmithSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.langsmith import (
    DEFAULT_BASE_URL,
    LangSmithResumeConfig,
    langsmith_source,
    normalize_base_url,
    validate_credentials as validate_langsmith_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LANGSMITH_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LangSmithSource(ResumableSource[LangSmithSourceConfig, LangSmithResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LANGSMITH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LANG_SMITH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="LangSmith",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter a LangSmith API key to sync your LLM traces, tracing projects, datasets, and feedback into the PostHog Data warehouse.

Create an API key in your [LangSmith settings](https://smith.langchain.com/settings) under **API Keys**.

Leave the **Host** field blank for the US cloud (`api.smith.langchain.com`). Set it to `https://eu.api.smith.langchain.com` for EU-region accounts, or to your own host for self-hosted deployments.""",
            iconPath="/static/services/langsmith.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/langsmith",
            keywords=["llm", "observability", "tracing", "langchain", "evals"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="lsv2_pt_...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="host",
                        label="Host",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://api.smith.langchain.com",
                        secret=False,
                    ),
                ],
            ),
        )

    @property
    def connection_host_fields(self) -> list[str]:
        # The API key is sent to `host`; retargeting it must re-require the key so a preserved
        # secret can't be redirected at a server the editor controls.
        return ["host"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your LangSmith API key is invalid or has been revoked. Create a new API key in your LangSmith settings, then reconnect.",
            "403 Client Error": "Your LangSmith API key does not have access to this workspace. Check the key's workspace scope, then reconnect.",
        }

    def get_schemas(
        self,
        config: LangSmithSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "runs":
                return (
                    "Traces and their nested spans (LLM calls, chains, tools) across every tracing "
                    "project. The first incremental sync only pulls the last 365 days"
                )
            if endpoint == "projects":
                return "Tracing projects (called sessions in the LangSmith API)"
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = LANGSMITH_ENDPOINTS[endpoint]
            supports_incremental = endpoint_config.window_param is not None and bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=supports_incremental,
                supports_append=supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                detected_primary_keys=endpoint_config.primary_keys,
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: LangSmithSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_langsmith_credentials(config.api_key, config.host or None, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LangSmithResumeConfig]:
        return ResumableSourceManager[LangSmithResumeConfig](inputs, LangSmithResumeConfig)

    def source_for_pipeline(
        self,
        config: LangSmithSourceConfig,
        resumable_source_manager: ResumableSourceManager[LangSmithResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return langsmith_source(
            api_key=config.api_key,
            base_url=normalize_base_url(config.host or DEFAULT_BASE_URL),
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            team_id=inputs.team_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
