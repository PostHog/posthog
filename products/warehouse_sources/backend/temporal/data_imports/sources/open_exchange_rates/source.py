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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    OpenExchangeRatesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.open_exchange_rates import (
    OpenExchangeRatesResumeConfig,
    open_exchange_rates_source,
    validate_credentials as validate_open_exchange_rates_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.settings import (
    OPEN_EXCHANGE_RATES_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OpenExchangeRatesSource(ResumableSource[OpenExchangeRatesSourceConfig, OpenExchangeRatesResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OPENEXCHANGERATES

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OPEN_EXCHANGE_RATES,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Open Exchange Rates",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Open Exchange Rates App ID to pull foreign-exchange reference rates into the PostHog Data warehouse.

Find your App ID in your [Open Exchange Rates dashboard](https://openexchangerates.org/account/app-ids).

The free plan is restricted to the `USD` base currency — a custom base currency requires a paid plan. The `historical` table walks one request per day from the start date, so a large backfill can use a lot of your monthly request quota.""",
            iconPath="/static/services/open_exchange_rates.png",
            docsUrl="https://posthog.com/docs/cdp/sources/open-exchange-rates",
            keywords=["oxr", "forex", "currency", "fx", "exchange rates"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="app_id",
                        label="App ID",
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
                        placeholder="USD",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date (historical backfill)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="YYYY-MM-DD",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid, missing, or revoked App ID surfaces as a 401 when `_request` raises. Retrying
            # can never fix a credential problem, so stop the sync. Match the stable status text and
            # base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://openexchangerates.org/api": "Your Open Exchange Rates App ID is invalid or has been revoked. Create a new App ID in your Open Exchange Rates dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://openexchangerates.org/api": "Your Open Exchange Rates App ID is missing or your account is restricted. Check the App ID and your account status, then reconnect.",
            # Open Exchange Rates returns 429 `not_allowed` for plan-gated features (e.g. a non-USD base
            # currency on the free plan), not a transient throttle — so it is permanent, not retryable.
            "429 Client Error: Too Many Requests for url: https://openexchangerates.org/api": "Your Open Exchange Rates plan does not allow this request (for example a non-USD base currency on the free plan). Upgrade your plan or set the base currency back to USD, then reconnect.",
        }

    def get_schemas(
        self,
        config: OpenExchangeRatesSourceConfig,
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
            for endpoint_config in OPEN_EXCHANGE_RATES_ENDPOINTS.values()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: OpenExchangeRatesSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_open_exchange_rates_credentials(config.app_id):
            return True, None

        # The probe also returns False on transient network/timeout errors, so don't claim the App ID
        # is definitively invalid — point at both possibilities.
        return (
            False,
            "Unable to verify your Open Exchange Rates App ID. Check that the App ID is correct and that openexchangerates.org is reachable.",
        )

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[OpenExchangeRatesResumeConfig]:
        return ResumableSourceManager[OpenExchangeRatesResumeConfig](inputs, OpenExchangeRatesResumeConfig)

    def source_for_pipeline(
        self,
        config: OpenExchangeRatesSourceConfig,
        resumable_source_manager: ResumableSourceManager[OpenExchangeRatesResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return open_exchange_rates_source(
            app_id=config.app_id,
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
