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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LangfuseSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.langfuse import (
    HOST_NOT_ALLOWED_ERROR,
    HTTP_NOT_ALLOWED_ERROR,
    REPEATED_CURSOR_ERROR,
    RESPONSE_LIMIT_ERROR,
    LangfuseResumeConfig,
    langfuse_source,
    validate_credentials as validate_langfuse_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LangfuseSource(ResumableSource[LangfuseSourceConfig, LangfuseResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://langfuse.com/docs/api-and-data-platform/features/public-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LANGFUSE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LANGFUSE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Langfuse",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Sync traces, observations, scores, sessions, prompts, and datasets from your Langfuse project.

Find your project API keys in your Langfuse **Project settings > API Keys**. Set the host to match your data region (`https://cloud.langfuse.com` for EU, `https://us.cloud.langfuse.com` for US) or your self-hosted instance URL.""",
            iconPath="/static/services/langfuse.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/langfuse",
            keywords=["llm", "observability", "traces", "prompts"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Host",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://cloud.langfuse.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="public_key",
                        label="Public key",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="pk-lf-...",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="secret_key",
                        label="Secret key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sk-lf-...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Langfuse API keys. Check the project public key and secret key, and make sure the host matches your Langfuse data region.",
            "403 Client Error": "Your Langfuse API keys do not have access to this resource. Check the keys and try again.",
            HOST_NOT_ALLOWED_ERROR: "The Langfuse host is not allowed. Please use a publicly reachable instance URL.",
            HTTP_NOT_ALLOWED_ERROR: "The Langfuse host must use HTTPS. Please update the host to use https://.",
            RESPONSE_LIMIT_ERROR: "The Langfuse host returned a response that was too large or too slow to download. Check that the host points at a real Langfuse instance.",
            # PAGE_LIMIT_ERROR is intentionally absent: it is retryable, so a huge sync resumes
            # from its checkpoint on the next attempt instead of failing permanently.
            REPEATED_CURSOR_ERROR: "The Langfuse host repeated a pagination cursor, so the sync was stopped to avoid looping. Check that the host points at a real Langfuse instance.",
        }

    def get_schemas(
        self,
        config: LangfuseSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: LangfuseSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_langfuse_credentials(config.host, config.public_key, config.secret_key, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LangfuseResumeConfig]:
        return ResumableSourceManager[LangfuseResumeConfig](inputs, LangfuseResumeConfig)

    def source_for_pipeline(
        self,
        config: LangfuseSourceConfig,
        resumable_source_manager: ResumableSourceManager[LangfuseResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return langfuse_source(
            host=config.host,
            public_key=config.public_key,
            secret_key=config.secret_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            team_id=inputs.team_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
