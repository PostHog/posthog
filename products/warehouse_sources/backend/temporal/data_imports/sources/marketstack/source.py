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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MarketstackSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.marketstack import (
    MarketstackResumeConfig,
    marketstack_source,
    validate_credentials as validate_marketstack_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.settings import MARKETSTACK_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MarketstackSource(ResumableSource[MarketstackSourceConfig, MarketstackResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MARKETSTACK

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A bad/blocked key surfaces as an HTTP 401 — retrying can never satisfy a credential
            # problem. Match the stable status text and base host.
            "401 Client Error: Unauthorized for url: https://api.marketstack.com": "Your Marketstack access key is invalid or has been deactivated. Generate a new key in your Marketstack dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.marketstack.com": "Your Marketstack plan does not grant access to this data. Upgrade your Marketstack plan or deselect the restricted tables, then reconnect.",
            # Marketstack also returns HTTP 200 with a body-level error envelope; these are raised as
            # MarketstackAPIError with a stable `[code]` token (see marketstack._fetch_page).
            "Marketstack API error [invalid_access_key]": "Your Marketstack access key is invalid or has been deactivated. Generate a new key in your Marketstack dashboard, then reconnect.",
            "Marketstack API error [missing_access_key]": "No Marketstack access key was supplied. Reconnect the source with a valid access key.",
            "Marketstack API error [inactive_user]": "Your Marketstack account is inactive. Reactivate it in your Marketstack dashboard, then reconnect.",
            "Marketstack API error [usage_limit_reached]": "Your Marketstack monthly request quota has been reached. Upgrade your plan or wait for the quota to reset, then resync.",
            "Marketstack API error [function_access_restricted]": "Your Marketstack plan does not grant access to this data (e.g. intraday requires a paid plan). Upgrade your Marketstack plan or deselect the restricted tables, then reconnect.",
            "Marketstack API error [https_access_restricted]": "Your Marketstack plan does not allow HTTPS access. Upgrade your Marketstack plan, then reconnect.",
            # The time-series tables need at least one symbol; without one the sync can never make
            # progress, so fail permanently with a fix-it message rather than retrying.
            "Marketstack API error [missing_symbols]": "One or more of the selected tables (EOD, intraday, splits, dividends) requires symbols. Add symbols to the source configuration, then resync.",
            "Marketstack API error [no_valid_symbols_provided]": "None of the configured symbols are valid Marketstack tickers. Check the symbols in the source configuration, then resync.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.marketstack.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: MarketstackSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint.name,
                # Only the time-series feeds expose a server-side date_from filter; reference tables
                # are full refresh only.
                supports_incremental=bool(endpoint.incremental_fields),
                supports_append=bool(endpoint.incremental_fields),
                incremental_fields=list(endpoint.incremental_fields),
                description=endpoint.description,
            )
            for endpoint in MARKETSTACK_ENDPOINTS.values()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: MarketstackSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_marketstack_credentials(config.access_key):
            return True, None

        return False, "Invalid Marketstack access key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MarketstackResumeConfig]:
        return ResumableSourceManager[MarketstackResumeConfig](inputs, MarketstackResumeConfig)

    def source_for_pipeline(
        self,
        config: MarketstackSourceConfig,
        resumable_source_manager: ResumableSourceManager[MarketstackResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return marketstack_source(
            access_key=config.access_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            symbols=config.symbols,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MARKETSTACK,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Marketstack",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Marketstack access key to pull end-of-day, intraday, splits, and dividends data plus market reference tables (tickers, exchanges, currencies, timezones) into the PostHog Data warehouse.

You can find your access key in your [Marketstack dashboard](https://marketstack.com/dashboard).

Add one or more comma-separated **symbols** (e.g. `AAPL,MSFT,TSLA`) to sync the EOD, intraday, splits, and dividends tables — those endpoints require at least one symbol. The reference tables don't need symbols.

Note: Marketstack pricing is a monthly request quota tied to your plan. Some tables (e.g. intraday) require a paid plan.""",
            iconPath="/static/services/marketstack.png",
            docsUrl="https://posthog.com/docs/cdp/sources/marketstack",
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
