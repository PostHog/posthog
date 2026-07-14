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
    LangfuseResumeConfig,
    langfuse_source,
    validate_credentials as validate_langfuse_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.settings import (
    DEFAULT_INCREMENTAL_LOOKBACK_SECONDS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LangfuseSource(ResumableSource[LangfuseSourceConfig, LangfuseResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LANGFUSE

    @property
    def connection_host_fields(self) -> list[str]:
        # `host` is where the stored secret key is sent; retargeting it must re-require the keys.
        return ["host"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Langfuse API keys. Please check the public/secret key pair and the region host, then reconnect.",
            "403 Client Error": "Your Langfuse API keys lack the required permissions. Please check the keys and try again.",
            HOST_NOT_ALLOWED_ERROR: "The Langfuse host is not allowed. Please use a publicly reachable host.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

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
                supports_incremental=bool(incremental_fields := INCREMENTAL_FIELDS.get(endpoint, [])),
                supports_append=bool(incremental_fields),
                incremental_fields=incremental_fields,
                # Langfuse's incremental filters are creation/start-time based, so re-read a
                # trailing window each run to pick up late-arriving updates (see settings.py).
                default_incremental_lookback_seconds=DEFAULT_INCREMENTAL_LOOKBACK_SECONDS
                if incremental_fields
                else None,
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
        return validate_langfuse_credentials(config.host, config.public_key, config.secret_key, schema_name, team_id)

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
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LANGFUSE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Langfuse",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["llm", "observability", "traces", "prompts", "evals"],
            caption="""Enter your Langfuse project API keys to pull your LLM observability data into the PostHog Data warehouse.

You can find the public and secret key in the Langfuse dashboard under **Project settings > API keys**.

Set the host to your Langfuse region — `https://cloud.langfuse.com` (EU, default), `https://us.cloud.langfuse.com` (US), `https://jp.cloud.langfuse.com` (JP), or `https://hipaa.cloud.langfuse.com` (HIPAA) — or to your own host if you self-host Langfuse.""",
            iconPath="/static/services/langfuse.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/langfuse",
            fields=cast(
                list[FieldType],
                [
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
                    SourceFieldInputConfig(
                        name="host",
                        label="Host",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://cloud.langfuse.com",
                        secret=False,
                    ),
                ],
            ),
        )
