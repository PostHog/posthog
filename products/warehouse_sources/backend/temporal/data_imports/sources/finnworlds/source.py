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
from products.warehouse_sources.backend.temporal.data_imports.sources.finnworlds.finnworlds import (
    finnworlds_source,
    parse_tickers,
    validate_credentials as validate_finnworlds_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.finnworlds.settings import (
    ENDPOINTS,
    FINNWORLDS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FinnworldsSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FinnworldsSource(SimpleSource[FinnworldsSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FINNWORLDS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Finnworlds answers an invalid/expired key with HTTP 200 and an error body, which the
            # transport raises as a FinnworldsAuthError carrying this prefix. Retrying can never fix a
            # credential problem, so fail the sync and tell the user to reconnect.
            "Finnworlds authentication failed": "Your Finnworlds API key is invalid or expired, or it lacks access to this dataset. Generate a new key and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.finnworlds.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: FinnworldsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Finnworlds exposes no server-side update cursor, so every endpoint is full refresh only.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                should_sync_default=FINNWORLDS_ENDPOINTS[endpoint].should_sync_default,
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: FinnworldsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            parse_tickers(config.tickers)
        except ValueError as exc:
            return False, str(exc)

        return validate_finnworlds_credentials(config.api_key)

    def source_for_pipeline(self, config: FinnworldsSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return finnworlds_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            tickers=parse_tickers(config.tickers),
            logger=inputs.logger,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FINNWORLDS,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Finnworlds",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Finnworlds API key to pull financial market data into the PostHog Data warehouse.

You can find your API key in your [Finnworlds dashboard](https://finnworlds.com/dashboard/).

Most datasets (fundamentals, prices, dividends, ratings) return data for one company per request, so enter the stock tickers you want to sync — the connector fetches each dataset for every ticker. Bond yields are global and ignore the ticker list.""",
            iconPath="/static/services/finnworlds.png",
            docsUrl="https://posthog.com/docs/cdp/sources/finnworlds",
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
                        name="tickers",
                        label="Tickers",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="AAPL, MSFT, GOOGL",
                        secret=False,
                    ),
                ],
            ),
        )
