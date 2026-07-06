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
from products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api.exchange_rates_api import (
    ExchangeRatesApiResumeConfig,
    exchange_rates_api_source,
    validate_credentials as validate_exchange_rates_api_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api.settings import (
    EXCHANGE_RATES_API_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    ExchangeRatesApiSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ExchangeRatesApiSource(ResumableSource[ExchangeRatesApiSourceConfig, ExchangeRatesApiResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EXCHANGERATESAPI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.EXCHANGE_RATES_API,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Exchange Rates API",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Exchange Rates API access key to pull foreign-exchange reference rates into the PostHog Data warehouse.

Create a key in your [exchangeratesapi.io dashboard](https://exchangeratesapi.io/dashboard).

The free plan is restricted to the `EUR` base currency — a custom base currency requires a paid plan. The `timeseries` table is capped at a 365-day range per request (backfills are chunked automatically) and may not be available on every plan.""",
            iconPath="/static/services/exchange_rates_api.png",
            docsUrl="https://posthog.com/docs/cdp/sources/exchange-rates-api",
            keywords=["exchangeratesapi", "forex", "currency", "fx"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_key",
                        label="Access key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="base_currency",
                        label="Base currency",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="EUR",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date (timeseries backfill)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="YYYY-MM-DD",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid, missing, or revoked access key surfaces as a 401 when `_request` calls
            # `raise_for_status()`. Retrying can never fix a credential problem, so stop the sync.
            # Match the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.exchangeratesapi.io": "Your Exchange Rates API access key is invalid or has been revoked. Create a new key in your exchangeratesapi.io dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.exchangeratesapi.io": "Your Exchange Rates API plan does not allow this request (for example a non-EUR base currency or the timeseries endpoint on the free plan). Upgrade your plan or adjust the source settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: ExchangeRatesApiSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint_config.name,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_incremental,
                incremental_fields=endpoint_config.incremental_fields,
                should_sync_default=endpoint_config.should_sync_default,
                description=endpoint_config.description,
            )
            for endpoint_config in EXCHANGE_RATES_API_ENDPOINTS.values()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: ExchangeRatesApiSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_exchange_rates_api_credentials(config.access_key):
            return True, None

        # The probe also returns False on transient network/timeout errors, so don't claim the key is
        # definitively invalid — point at both possibilities.
        return (
            False,
            "Unable to verify your Exchange Rates API access key. Check that the key is correct and that exchangeratesapi.io is reachable.",
        )

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[ExchangeRatesApiResumeConfig]:
        return ResumableSourceManager[ExchangeRatesApiResumeConfig](inputs, ExchangeRatesApiResumeConfig)

    def source_for_pipeline(
        self,
        config: ExchangeRatesApiSourceConfig,
        resumable_source_manager: ResumableSourceManager[ExchangeRatesApiResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return exchange_rates_api_source(
            access_key=config.access_key,
            endpoint=inputs.schema_name,
            base_currency=config.base_currency or "",
            start_date=config.start_date,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
