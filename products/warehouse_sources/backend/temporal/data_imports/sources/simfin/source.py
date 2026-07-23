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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.simfin import SimFinSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.simfin.settings import SIMFIN_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.simfin.simfin import (
    simfin_source,
    validate_credentials as validate_simfin_credentials,
    validate_tickers,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SimFinSource(SimpleSource[SimFinSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://simfin.readme.io/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SIMFIN

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://backend.simfin.com": "Your SimFin API key is invalid or your account e-mail is not confirmed. Check the key in the SimFin app and reconnect.",
            "403 Client Error: Forbidden for url: https://backend.simfin.com": "Your SimFin plan does not include access to this dataset. Upgrade your SimFin plan or deselect the table.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.simfin.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SimFinSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # SimFin has no server-side change cursor (statement/price date filters scope the record's
        # own date, and price history is split-adjusted retroactively), so every table is full
        # refresh only.
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
            for endpoint in SIMFIN_ENDPOINTS.values()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: SimFinSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        _, tickers_error = validate_tickers(config.tickers)
        if tickers_error:
            return False, tickers_error

        if validate_simfin_credentials(config.api_key, self.default_version):
            return True, None

        return False, "Invalid SimFin API key"

    def source_for_pipeline(self, config: SimFinSourceConfig, inputs: SourceInputs) -> SourceResponse:
        # Re-validate here so a previously-saved oversized ticker list can't trigger a runaway sync.
        tickers, tickers_error = validate_tickers(config.tickers)
        if tickers_error:
            raise ValueError(f"SimFin source misconfigured: {tickers_error}")

        return simfin_source(
            api_key=config.api_key,
            tickers=tickers,
            endpoint=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            logger=inputs.logger,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SIM_FIN,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="SimFin",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["financial data", "fundamentals", "stocks", "equities", "share prices"],
            caption="""Enter your SimFin API key and the stock tickers you want to track to pull standardized financial statements, share prices and company data into the PostHog Data warehouse.

You can find your API key in the [SimFin app](https://app.simfin.com/data-api) (confirm your account e-mail first).

Note: each selected table costs one request per ticker on every sync, and SimFin rate limits requests per second by plan tier. Historical depth and some datasets depend on your SimFin plan.""",
            iconPath="/static/services/simfin.png",
            docsUrl="https://posthog.com/docs/cdp/sources/simfin",
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
                        label="Tickers (comma-separated)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="AAPL, MSFT, GOOG",
                        secret=False,
                    ),
                ],
            ),
        )
