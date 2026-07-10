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
from products.warehouse_sources.backend.temporal.data_imports.sources.clari.clari import (
    ClariResumeConfig,
    clari_source,
    validate_credentials as validate_clari_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clari.settings import (
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ClariSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ClariSource(ResumableSource[ClariSourceConfig, ClariResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = ("v4",)
    default_version = "v4"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLARI

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.clari.com": "Clari authentication failed. Please check your API key.",
            "403 Client Error: Forbidden for url: https://api.clari.com": "Clari denied access. Please check your API key's permissions.",
            "404 Client Error: Not Found for url: https://api.clari.com/v4/export/forecast": "Clari forecast not found. Please check your forecast ID (copy it from the Forecast tab URL in Clari).",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CLARI,
            category=DataWarehouseSourceCategory.SALES,
            label="Clari",
            caption="""Connect your Clari account to pull your revenue data into the PostHog Data warehouse.

Generate an API key in Clari under your account's API settings. The forecast ID is in the URL when viewing a forecast tab in Clari (e.g. `app.clari.com/forecast/<forecast-id>`). Note: Clari retains audit events for ~30 days and caps forecast exports at roughly 1,000 per rolling 30 days, so avoid very frequent syncs of the forecast table.""",
            iconPath="/static/services/clari.png",
            docsUrl="https://posthog.com/docs/cdp/sources/clari",
            releaseStatus=ReleaseStatus.ALPHA,
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
                    SourceFieldInputConfig(
                        name="forecast_id",
                        label="Forecast ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="net_bookings",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.clari.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ClariSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: ClariSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_clari_credentials(config.api_key):
            return True, None

        return False, "Invalid Clari credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ClariResumeConfig]:
        return ResumableSourceManager[ClariResumeConfig](inputs, ClariResumeConfig)

    def source_for_pipeline(
        self,
        config: ClariSourceConfig,
        resumable_source_manager: ResumableSourceManager[ClariResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return clari_source(
            api_key=config.api_key,
            forecast_id=config.forecast_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
