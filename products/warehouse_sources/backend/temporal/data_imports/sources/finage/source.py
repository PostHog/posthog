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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.finage.finage import (
    DEFAULT_START_DATE,
    FinageConfigError,
    finage_source,
    parse_symbols,
    validate_credentials as validate_finage_credentials,
    validate_source_config,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.finage.settings import ENDPOINTS, FINAGE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FinageSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

_ENDPOINT_DESCRIPTIONS = {
    "last_quote": "Latest bid/ask quote per symbol. Point-in-time snapshot, full refresh.",
    "last_trade": "Latest trade (price and size) per symbol. Point-in-time snapshot, full refresh.",
    "aggregates": "Historical daily OHLCV bars per symbol from the backfill start date. Full refresh.",
}


@SourceRegistry.register
class FinageSource(SimpleSource[FinageSourceConfig]):
    # `get_schemas` iterates a static endpoint catalog with no I/O, so the table list is safe to render
    # in public docs without credentials.
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FINAGE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FINAGE,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Finage",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Finage API key and the symbols you want to sync to pull market data into the PostHog Data warehouse.

You can find your API key in the [Finage dashboard](https://finage.co.uk/dashboard) after subscribing to a plan. The key needs access to the **US stocks** endpoints.""",
            iconPath="/static/services/finage.png",
            docsUrl="https://posthog.com/docs/cdp/sources/finage",
            keywords=["stocks", "market data", "ohlcv", "finance"],
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
                        placeholder="AAPL,MSFT,TSLA",
                        secret=False,
                        caption="Comma-separated list of US stock symbols to sync, e.g. `AAPL,MSFT,TSLA`.",
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Backfill start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder=DEFAULT_START_DATE,
                        secret=False,
                        caption=f"Earliest date (`YYYY-MM-DD`) to pull historical aggregate bars from. Defaults to `{DEFAULT_START_DATE}`.",
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.finage.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.finage.co.uk": "Your Finage API key is invalid or has been revoked. Generate a new key in your Finage dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.finage.co.uk": "Your Finage plan does not include access to this data. Upgrade your Finage subscription or remove the affected tables, then reconnect.",
        }

    def get_schemas(
        self,
        config: FinageSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = FINAGE_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                should_sync_default=endpoint_config.should_sync_default,
                detected_primary_keys=endpoint_config.primary_keys,
                description=_ENDPOINT_DESCRIPTIONS.get(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: FinageSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            validate_source_config(parse_symbols(config.symbols), config.start_date or DEFAULT_START_DATE)
        except FinageConfigError as exc:
            return False, str(exc)

        status = validate_finage_credentials(config.api_key)

        if status == 200:
            return True, None
        if status == 401:
            return False, "Invalid Finage API key. Generate a new key in your Finage dashboard and try again."
        if status == 403:
            # Valid token, but the plan doesn't cover this endpoint. Accept at source-create (the user
            # can upgrade later); only fail when validating a specific schema.
            if schema_name is None:
                return True, None
            return False, "Your Finage plan does not include access to this data. Upgrade your subscription to sync it."

        return False, "Could not validate Finage credentials. Please check your API key and try again."

    def source_for_pipeline(self, config: FinageSourceConfig, inputs: SourceInputs) -> SourceResponse:
        symbols = parse_symbols(config.symbols)
        start_date = config.start_date or DEFAULT_START_DATE
        # Re-validate here so a source saved before these guards existed can't fan out a runaway sync.
        validate_source_config(symbols, start_date)
        return finage_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            symbols=symbols,
            start_date=start_date,
            logger=inputs.logger,
        )
