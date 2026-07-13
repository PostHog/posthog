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
from products.warehouse_sources.backend.temporal.data_imports.sources.alpha_vantage.alpha_vantage import (
    alpha_vantage_source,
    validate_credentials as validate_alpha_vantage_credentials,
    validate_symbols,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.alpha_vantage.settings import (
    ALPHA_VANTAGE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AlphaVantageSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AlphaVantageSource(SimpleSource[AlphaVantageSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ALPHAVANTAGE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Alpha Vantage returns HTTP 200 with an "Information" envelope when the daily quota is
            # exhausted or the dataset is premium-only; retrying within the same run can never satisfy
            # it, so fail fast. The next scheduled sync retries once the quota resets.
            "Alpha Vantage API error [rate_limit_or_premium]": "Alpha Vantage returned a rate-limit or premium-only message. The free tier is limited to ~25 requests/day and some datasets require a paid plan. Wait for the quota to reset or upgrade your plan, then resync.",
            "Alpha Vantage API error [unexpected_response]": "Alpha Vantage returned an unexpected response. Please try again later.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.alpha_vantage.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AlphaVantageSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Alpha Vantage has no server-side updated-at cursor, so every table is full refresh only.
        schemas = [
            SourceSchema(
                name=endpoint.name,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                detected_primary_keys=endpoint.primary_keys,
                should_sync_default=endpoint.should_sync_default,
                description=endpoint.description,
            )
            for endpoint in ALPHA_VANTAGE_ENDPOINTS.values()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: AlphaVantageSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        _, symbols_error = validate_symbols(config.symbols)
        if symbols_error:
            return False, symbols_error

        if validate_alpha_vantage_credentials(config.api_key):
            return True, None

        return False, "Invalid Alpha Vantage API key"

    def source_for_pipeline(self, config: AlphaVantageSourceConfig, inputs: SourceInputs) -> SourceResponse:
        # Re-validate here so a previously-saved oversized symbol list can't trigger a runaway sync.
        symbols, symbols_error = validate_symbols(config.symbols)
        if symbols_error:
            raise ValueError(f"Alpha Vantage source misconfigured: {symbols_error}")

        return alpha_vantage_source(
            api_key=config.api_key,
            symbols=symbols,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ALPHA_VANTAGE,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Alpha Vantage",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            keywords=["stocks", "market data", "financial", "equities", "fundamentals"],
            caption="""Enter your Alpha Vantage API key and the stock symbols you want to track to pull market data and company fundamentals into the PostHog Data warehouse.

You can claim a free API key on the [Alpha Vantage support page](https://www.alphavantage.co/support/#api-key).

Note: the free tier is limited to roughly 25 requests per day, and each selected table costs one request per symbol on every sync. Some datasets require a paid plan.""",
            iconPath="/static/services/alpha_vantage.png",
            docsUrl="https://posthog.com/docs/cdp/sources/alpha-vantage",
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
                        label="Symbols (comma-separated)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="IBM, AAPL, MSFT",
                        secret=False,
                    ),
                ],
            ),
        )
