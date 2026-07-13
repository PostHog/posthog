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
from products.warehouse_sources.backend.temporal.data_imports.sources.alguna.alguna import (
    ALGUNA_BASE_URL,
    AlgunaResumeConfig,
    alguna_source,
    validate_credentials as validate_alguna_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.alguna.settings import (
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AlgunaSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AlgunaSource(ResumableSource[AlgunaSourceConfig, AlgunaResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ALGUNA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ALGUNA,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Alguna",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Alguna API key to automatically pull your Alguna billing data into the PostHog Data warehouse.

You can create an API key in your Alguna dashboard under Settings > Credentials.
""",
            iconPath="/static/services/alguna.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/alguna",
            keywords=["billing", "invoices", "subscriptions", "usage-based", "cpq"],
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
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.alguna.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            f"401 Client Error: Unauthorized for url: {ALGUNA_BASE_URL}": "Your Alguna API key is invalid or has been revoked. Create a new API key in your Alguna dashboard under Settings > Credentials, then reconnect.",
            f"403 Client Error: Forbidden for url: {ALGUNA_BASE_URL}": "Your Alguna API key does not have permission to read this data. Check the key in your Alguna dashboard under Settings > Credentials, then reconnect.",
        }

    def get_schemas(
        self,
        config: AlgunaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: AlgunaSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_alguna_credentials(config.api_key):
            return True, None

        return False, "Invalid Alguna API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AlgunaResumeConfig]:
        return ResumableSourceManager[AlgunaResumeConfig](inputs, AlgunaResumeConfig)

    def source_for_pipeline(
        self,
        config: AlgunaSourceConfig,
        resumable_source_manager: ResumableSourceManager[AlgunaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return alguna_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
