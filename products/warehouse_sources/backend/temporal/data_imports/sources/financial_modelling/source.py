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
from products.warehouse_sources.backend.temporal.data_imports.sources.financial_modelling.financial_modelling import (
    FinancialModellingResumeConfig,
    financial_modelling_source,
    parse_symbols,
    validate_credentials as validate_financial_modelling_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.financial_modelling.settings import (
    ENDPOINTS,
    FINANCIAL_MODELLING_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    FinancialModellingSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FinancialModellingSource(ResumableSource[FinancialModellingSourceConfig, FinancialModellingResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FINANCIALMODELLING

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FINANCIAL_MODELLING,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Financial Modeling Prep",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Financial Modeling Prep API key to pull market and company financial data into the PostHog Data warehouse.

You can find your API key in your [Financial Modeling Prep dashboard](https://site.financialmodelingprep.com/developer/docs/dashboard).

The symbol-keyed tables (company profiles, financial statements, historical prices) are fetched once per ticker you list below, so keep the list focused — free-tier keys are heavily rate-limited.""",
            iconPath="/static/services/financial_modelling.png",
            docsUrl="https://posthog.com/docs/cdp/sources/financial-modelling",
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
                        name="symbols",
                        label="Symbols",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="AAPL, MSFT, GOOGL",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.financial_modelling.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://financialmodelingprep.com": "Your Financial Modeling Prep API key is invalid or has been revoked. Generate a new key in your Financial Modeling Prep dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://financialmodelingprep.com": "Your Financial Modeling Prep plan does not grant access to this data. Upgrade your plan or deselect the affected tables, then reconnect.",
            "Financial Modeling Prep API returned an error response": "Financial Modeling Prep returned an error for this table — usually because your plan does not include this data or your API key is invalid. Upgrade your plan or deselect the affected tables, then reconnect.",
        }

    def get_schemas(
        self,
        config: FinancialModellingSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = FINANCIAL_MODELLING_ENDPOINTS[endpoint]
            has_incremental = endpoint_config.supports_date_window and bool(endpoint_config.incremental_fields)
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=endpoint_config.incremental_fields,
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: FinancialModellingSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_financial_modelling_credentials(config.api_key):
            return True, None
        return False, "Invalid Financial Modeling Prep API key"

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[FinancialModellingResumeConfig]:
        return ResumableSourceManager[FinancialModellingResumeConfig](inputs, FinancialModellingResumeConfig)

    def source_for_pipeline(
        self,
        config: FinancialModellingSourceConfig,
        resumable_source_manager: ResumableSourceManager[FinancialModellingResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return financial_modelling_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            symbols=parse_symbols(config.symbols),
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
