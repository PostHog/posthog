from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.twelvedata import (
    TwelveDataSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_data.settings import (
    DEFAULT_TIME_SERIES_INTERVAL,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    MAX_SYMBOLS,
    TIME_SERIES_INTERVALS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_data.twelve_data import (
    TwelveDataResumeConfig,
    parse_symbols,
    twelve_data_source,
    validate_credentials as validate_twelve_data_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TwelveDataSource(ResumableSource[TwelveDataSourceConfig, TwelveDataResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://twelvedata.com/docs"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TWELVEDATA

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "Twelve Data API error 401": "Your Twelve Data API key is invalid or missing. Check the key and reconnect the source.",
            "Twelve Data API error 403": "Your Twelve Data plan does not include access to this data. Upgrade your plan or deselect the table.",
            "Twelve Data API error 404": "Twelve Data could not find one of the configured symbols. Check the symbols list in the source settings.",
            "Twelve Data symbol limit exceeded": f"Too many symbols configured for the Twelve Data source. Reduce the list to at most {MAX_SYMBOLS} symbols.",
        }

    def get_retryable_errors(self) -> set[str]:
        # Credit-based rate limiting — the per-minute quota restores itself, so the sync recovers
        # on the next Temporal attempt.
        return {"Twelve Data API error 429"}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_data.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: TwelveDataSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: TwelveDataSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        symbols = parse_symbols(config.symbols)
        if not symbols:
            return False, "Enter at least one symbol to sync"
        if len(symbols) > MAX_SYMBOLS:
            return False, f"Too many symbols — the maximum is {MAX_SYMBOLS}"

        return validate_twelve_data_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TwelveDataResumeConfig]:
        return ResumableSourceManager[TwelveDataResumeConfig](inputs, TwelveDataResumeConfig)

    def source_for_pipeline(
        self,
        config: TwelveDataSourceConfig,
        resumable_source_manager: ResumableSourceManager[TwelveDataResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return twelve_data_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            symbols=parse_symbols(config.symbols),
            interval=config.interval,
            config_start_date=(config.start_date or "").strip() or None,
            resumable_source_manager=resumable_source_manager,
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TWELVE_DATA,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Twelve Data",
            caption="Import market data from Twelve Data: instrument catalogs, historical prices, quotes, dividends, splits, and earnings.",
            docsUrl="https://posthog.com/docs/cdp/sources/twelve-data",
            iconPath="/static/services/twelve_data.png",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["stocks", "forex", "crypto", "market data", "twelvedata"],
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
                        placeholder="AAPL, MSFT, EUR/USD",
                        secret=False,
                        caption=f"Comma-separated list of up to {MAX_SYMBOLS} symbols to sync in the time series, quotes, dividends, splits, and earnings tables. Each Twelve Data request is charged per symbol, so a longer list uses more of your plan's API credits.",
                    ),
                    SourceFieldSelectConfig(
                        name="interval",
                        label="Time series interval",
                        required=True,
                        defaultValue=DEFAULT_TIME_SERIES_INTERVAL,
                        options=[
                            SourceFieldSelectConfigOption(label=interval, value=interval)
                            for interval in TIME_SERIES_INTERVALS
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Time series start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="2020-01-01",
                        secret=False,
                        caption="Backfill time series history from this date. Leave empty to sync only the most recent 5,000 bars per symbol.",
                    ),
                ],
            ),
        )
