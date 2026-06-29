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
from products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.chartmogul import (
    ChartMogulResumeConfig,
    chartmogul_source,
    validate_credentials as validate_chartmogul_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.settings import (
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ChartMogulSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ChartMogulSource(ResumableSource[ChartMogulSourceConfig, ChartMogulResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CHARTMOGUL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CHART_MOGUL,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="ChartMogul",
            caption="""Enter your ChartMogul API key to pull your subscription analytics data into the PostHog Data warehouse.

You can find your API key in your [ChartMogul admin settings](https://app.chartmogul.com/#/admin/api).""",
            iconPath="/static/services/chartmogul.png",
            docsUrl="https://posthog.com/docs/cdp/sources/chartmogul",
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
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.chartmogul.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ChartMogulSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0,
                supports_append=len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: ChartMogulSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_chartmogul_credentials(config.api_key):
            return True, None

        return False, "Invalid ChartMogul API key"

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.chartmogul.com": "Your ChartMogul API key is invalid or expired. Please generate a new key and reconnect.",
            "403 Client Error: Forbidden for url: https://api.chartmogul.com": "Your ChartMogul API key does not have the required permissions. Please check the key and try again.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ChartMogulResumeConfig]:
        return ResumableSourceManager[ChartMogulResumeConfig](inputs, ChartMogulResumeConfig)

    def source_for_pipeline(
        self,
        config: ChartMogulSourceConfig,
        resumable_source_manager: ResumableSourceManager[ChartMogulResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return chartmogul_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
