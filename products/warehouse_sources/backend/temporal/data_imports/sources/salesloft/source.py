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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SalesLoftSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.salesloft import (
    SalesloftResumeConfig,
    salesloft_source,
    validate_credentials as validate_salesloft_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SalesLoftSource(ResumableSource[SalesLoftSourceConfig, SalesloftResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SALESLOFT

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Your Salesloft API key is invalid or expired. Please generate a new key and reconnect.",
            "403 Client Error: Forbidden for url": "Your Salesloft API key does not have access to this resource. Please check the key's permissions and try again.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SALES_LOFT,
            category=DataWarehouseSourceCategory.SALES,
            label="Salesloft",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Salesloft API key to pull your Salesloft data into the PostHog Data warehouse.

You can create an API key in your [Salesloft account](https://accounts.salesloft.com/oauth/applications) under **Settings → Integrations → API**. Paste the **API key** (a Bearer token) below.""",
            iconPath="/static/services/salesloft.png",
            docsUrl="https://posthog.com/docs/cdp/sources/salesloft",
            # Kept hidden until end-to-end sync is verified against a live Salesloft account
            # (endpoint behavior was validated against API docs + the Airbyte connector, not curl).
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

    def get_schemas(
        self,
        config: SalesLoftSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                # Only the incremental endpoints carry advertised fields; full-refresh ones are empty.
                supports_incremental=bool(INCREMENTAL_FIELDS[endpoint]),
                supports_append=bool(INCREMENTAL_FIELDS[endpoint]),
                incremental_fields=INCREMENTAL_FIELDS[endpoint],
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: SalesLoftSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_salesloft_credentials(config.api_key):
            return True, None

        return False, "Invalid Salesloft API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SalesloftResumeConfig]:
        return ResumableSourceManager[SalesloftResumeConfig](inputs, SalesloftResumeConfig)

    def source_for_pipeline(
        self,
        config: SalesLoftSourceConfig,
        resumable_source_manager: ResumableSourceManager[SalesloftResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return salesloft_source(
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
