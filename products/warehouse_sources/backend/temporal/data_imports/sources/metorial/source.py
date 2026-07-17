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
    METORIAL_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MetorialSource(ResumableSource[MetorialSourceConfig, MetorialResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = ("2025-01-01",)
    default_version = "2025-01-01"
    api_docs_url = "https://metorial.com/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.METORIAL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.METORIAL,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Metorial",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Metorial secret API key to pull your Metorial MCP data into the PostHog Data warehouse.

Create a secret API key (`metorial_sk_...`) in your [Metorial dashboard](https://metorial.com). Keys are project-scoped, so connect one source per project you want to sync. A publishable key (`metorial_pk_...`) only exposes public data and will not work here.""",
            iconPath="/static/services/metorial.png",
            docsUrl="https://posthog.com/docs/cdp/sources/metorial",
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
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.metorial.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError from `raise_for_status()`. Retrying can never fix
            # a bad key or a key missing project scope, so stop the sync. Match the stable status text
            # and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.metorial.com": "Your Metorial API key is invalid or has been revoked. Create a new secret API key in your Metorial dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.metorial.com": "Your Metorial API key does not have access to this project's data. Use a secret key (metorial_sk_...) for the project you want to sync, then reconnect.",
        }

    def get_schemas(
        self,
        config: MetorialSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = METORIAL_ENDPOINTS[endpoint]
            has_incremental = len(endpoint_config.incremental_fields) > 0
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=endpoint_config.supports_append,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: MetorialSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_metorial_credentials(config.api_key):
            return True, None

        return False, "Invalid Metorial API key"

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
