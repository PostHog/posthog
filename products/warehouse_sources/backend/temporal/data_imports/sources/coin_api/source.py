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
from products.warehouse_sources.backend.temporal.data_imports.sources.coin_api.coin_api import (
    CoinApiResumeConfig,
    coin_api_source,
    validate_credentials as validate_coin_api_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coin_api.settings import (
    COIN_API_ENDPOINTS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CoinApiSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CoinApiSource(ResumableSource[CoinApiSourceConfig, CoinApiResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.COINAPI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.COIN_API,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="CoinAPI",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your CoinAPI key to pull cryptocurrency market data into the PostHog Data warehouse.

Create a key in the [CoinAPI customer portal](https://customer.coinapi.io/). CoinAPI uses a credit/quota-based (pay-as-you-go) model with a daily credit limit, so large time-series tables can consume significant credits.

The **reference** tables (assets, exchanges, symbols) and **exchange rates** sync with just an API key. The **OHLCV** and **trades** history tables are scoped to a single market, so set the **Symbol ID** field (and, for OHLCV, the **Period ID**) to enable them.""",
            iconPath="/static/services/coin_api.png",
            docsUrl="https://posthog.com/docs/cdp/sources/coin-api",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="00000000-0000-0000-0000-000000000000",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="exchange_rate_base_asset",
                        label="Exchange rate base asset",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="USD",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="symbol_id",
                        label="Symbol ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="BITSTAMP_SPOT_BTC_USD",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="period_id",
                        label="Period ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="1DAY",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="2024-01-01T00:00:00",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.coin_api.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or malformed key surfaces as a 401 when `_fetch` calls `raise_for_status()`.
            # Retrying can never fix a credential problem. Match the stable status text and base host.
            "401 Client Error: Unauthorized for url: https://rest.coinapi.io": "Your CoinAPI key is invalid or incorrectly formatted. Create a new key in the CoinAPI customer portal, then reconnect.",
            # 403 means the key is genuine but its plan doesn't grant access to this data.
            "403 Client Error: Forbidden for url: https://rest.coinapi.io": "Your CoinAPI key does not have access to this data. Check that your CoinAPI subscription covers this endpoint, then reconnect.",
        }

    def get_schemas(
        self,
        config: CoinApiSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = COIN_API_ENDPOINTS[endpoint]
            is_timeseries = endpoint_config.kind == "timeseries"
            description = None
            if endpoint_config.requires_symbol:
                description = "Requires a Symbol ID on the source. Only syncs the configured symbol."
            # CoinAPI's time-series endpoints filter server-side on `time_start`, so they're genuinely
            # incremental. Reference/snapshot endpoints expose no such filter — full refresh only.
            return SourceSchema(
                name=endpoint,
                supports_incremental=is_timeseries,
                supports_append=is_timeseries,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                description=description,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: CoinApiSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_coin_api_credentials(config.api_key):
            return True, None

        # The probe also returns False on transient network/timeout errors, so don't claim the key is
        # definitively invalid — point at both possibilities.
        return (
            False,
            "Unable to verify your CoinAPI key. Check that the key is correct and that CoinAPI is reachable.",
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CoinApiResumeConfig]:
        return ResumableSourceManager[CoinApiResumeConfig](inputs, CoinApiResumeConfig)

    def source_for_pipeline(
        self,
        config: CoinApiSourceConfig,
        resumable_source_manager: ResumableSourceManager[CoinApiResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return coin_api_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            symbol_id=config.symbol_id or "",
            period_id=config.period_id or "1DAY",
            exchange_rate_base_asset=config.exchange_rate_base_asset or "USD",
            start_date=config.start_date or "",
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
