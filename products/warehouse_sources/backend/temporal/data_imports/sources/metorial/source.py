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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MetorialSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.metorial.metorial import (
    MetorialResumeConfig,
    metorial_source,
    validate_credentials as validate_metorial_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metorial.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MetorialSource(ResumableSource[MetorialSourceConfig, MetorialResumeConfig]):
    """Metorial (MCP hosting platform) import source.

    Pull-only: Metorial's callback destinations are CRUD-manageable webhooks, but they deliver
    provider *trigger* events (e.g. an upstream MCP provider's `message.created`), not change
    events for the resources we sync — so the WebhookSource mixin doesn't apply here.
    """

    # Static endpoint catalog with no I/O — safe to render in public docs.
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.METORIAL

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid or expired Metorial API key. Please generate a new secret key and reconnect.",
            "403 Client Error": "Your Metorial API key does not have the required permissions. Use a secret key (metorial_sk_...) from your project dashboard.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.metorial.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: MetorialSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas: list[SourceSchema] = []
        for endpoint in ENDPOINTS:
            if names is not None and endpoint not in names:
                continue

            incremental_fields = INCREMENTAL_FIELDS.get(endpoint, [])
            supports_incremental = bool(incremental_fields)
            schemas.append(
                SourceSchema(
                    name=endpoint,
                    supports_incremental=supports_incremental,
                    supports_append=supports_incremental,
                    incremental_fields=incremental_fields,
                )
            )
        return schemas

    def validate_credentials(
        self, config: MetorialSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_metorial_credentials(api_key=config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MetorialResumeConfig]:
        return ResumableSourceManager[MetorialResumeConfig](inputs, MetorialResumeConfig)

    def source_for_pipeline(
        self,
        config: MetorialSourceConfig,
        resumable_source_manager: ResumableSourceManager[MetorialResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return metorial_source(
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

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.METORIAL,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Metorial",
            caption="""Sync MCP sessions, messages, tool calls, errors, provider runs, providers, and deployments from your Metorial project.

Use a **secret** API key (`metorial_sk_...`) generated from your Metorial dashboard — publishable keys (`metorial_pk_...`) cannot read project data.
""",
            docsUrl="https://posthog.com/docs/cdp/sources/metorial",
            iconPath="/static/services/metorial.png",
            keywords=["mcp", "ai infrastructure", "agents", "observability"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Secret API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="metorial_sk_...",
                        secret=True,
                    ),
                ],
            ),
            unreleasedSource=True,
            releaseStatus=ReleaseStatus.ALPHA,
        )
