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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.stockdata import (
    StockDataSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stockdata.settings import STOCKDATA_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.stockdata.stockdata import (
    StockDataResumeConfig,
    stockdata_source,
    validate_credentials as validate_stockdata_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class StockDataSource(ResumableSource[StockDataSourceConfig, StockDataResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://www.stockdata.org/documentation"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STOCKDATA

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.stockdata.org": "Your StockData.org API token is invalid. Generate a new token in your StockData.org dashboard, then reconnect.",
            "402 Client Error: Payment Required for url: https://api.stockdata.org": "Your StockData.org plan's usage limit has been reached. Upgrade your plan or wait for the quota to reset, then resync.",
            "403 Client Error: Forbidden for url: https://api.stockdata.org": "Your StockData.org plan does not grant access to this data (e.g. dividends and splits require a Standard or higher plan). Upgrade your plan or deselect the restricted tables, then resync.",
            # The price tables need at least one symbol; without one the sync can never make
            # progress, so fail permanently with a fix-it message rather than retrying.
            "StockData.org API error [missing_symbols]": "One or more of the selected tables (quote, EOD, intraday, dividends, splits) requires symbols. Add symbols to the source configuration, then resync.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.stockdata.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: StockDataSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint.name,
                # Only news (published_after) and the EOD/intraday price feeds (date_from) expose a
                # server-side date filter; quote, dividends, and splits are full refresh only.
                supports_incremental=bool(endpoint.incremental_fields),
                supports_append=bool(endpoint.incremental_fields),
                incremental_fields=list(endpoint.incremental_fields),
                description=endpoint.description,
            )
            for endpoint in STOCKDATA_ENDPOINTS.values()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: StockDataSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_stockdata_credentials(config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[StockDataResumeConfig]:
        return ResumableSourceManager[StockDataResumeConfig](inputs, StockDataResumeConfig)

    def source_for_pipeline(
        self,
        config: StockDataSourceConfig,
        resumable_source_manager: ResumableSourceManager[StockDataResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return stockdata_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            symbols=config.symbols,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.STOCK_DATA,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="StockData.org",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your StockData.org API token to pull market news with sentiment plus quote, end-of-day, intraday, dividend, and split price data into the PostHog Data warehouse.

You can find your API token in your [StockData.org dashboard](https://www.stockdata.org/dashboard).

Add one or more comma-separated **symbols** (e.g. `AAPL,MSFT,TSLA`) to sync the price tables (quote, EOD, intraday, dividends, splits) — those endpoints require at least one symbol. The news table works without symbols (all market news) and is filtered to your symbols when they are set.

Note: StockData.org plans are limited by daily request quotas (100 requests/day on the free plan), and some tables (dividends, splits) require a Standard or higher plan.""",
            iconPath="/static/services/stockdata.png",
            docsUrl="https://posthog.com/docs/cdp/sources/stockdata",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="symbols",
                        label="Symbols",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="AAPL,MSFT,TSLA",
                        secret=False,
                    ),
                ],
            ),
        )
