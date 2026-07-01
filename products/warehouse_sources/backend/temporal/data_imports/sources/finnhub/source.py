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
from products.warehouse_sources.backend.temporal.data_imports.sources.finnhub.finnhub import (
    finnhub_source,
    validate_credentials as validate_finnhub_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.finnhub.settings import (
    ENDPOINTS,
    FINNHUB_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FinnhubSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FinnhubSource(SimpleSource[FinnhubSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FINNHUB

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A bad or revoked key surfaces as a 401 when `_fetch` calls `raise_for_status()`;
            # an endpoint outside the plan tier surfaces as a 403. Neither is fixable by retrying,
            # so stop the sync. Match the stable status text and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://finnhub.io": "Your Finnhub API key is invalid or has been revoked. Create a new key in your Finnhub dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://finnhub.io": "Your Finnhub plan does not include access to this data. Upgrade your plan or deselect the affected tables, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.finnhub.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: FinnhubSourceConfig,
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
                should_sync_default=FINNHUB_ENDPOINTS[endpoint].should_sync_default,
                description=FINNHUB_ENDPOINTS[endpoint].description,
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: FinnhubSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_finnhub_credentials(config.api_key, schema_name)

    def source_for_pipeline(self, config: FinnhubSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return finnhub_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            symbols=config.symbols,
            exchange=config.exchange,
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FINNHUB,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Finnhub",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Finnhub API key to pull market and company financial data into the PostHog Data warehouse.

Create a free API key in your [Finnhub dashboard](https://finnhub.io/dashboard).

Per-company tables (company profile, quote, company news, basic financials, recommendation trends, earnings surprises) are synced for each ticker you list in **Symbols**. Market-wide tables (stock symbols, market news, IPO calendar, earnings calendar, countries) sync without any symbols.

Note: the free tier is rate limited to 60 requests/minute, and some endpoints require a paid plan.""",
            iconPath="/static/services/finnhub.png",
            docsUrl="https://posthog.com/docs/cdp/sources/finnhub",
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
                        required=False,
                        placeholder="AAPL, MSFT, GOOGL",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="exchange",
                        label="Exchange (for the stock symbols table)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="US",
                        secret=False,
                    ),
                ],
            ),
        )
