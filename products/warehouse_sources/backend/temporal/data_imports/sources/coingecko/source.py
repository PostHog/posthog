from typing import Optional, cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.coingecko import (
    NO_COINS_ERROR,
    PLAN_DEMO,
    PLAN_PRO,
    CoinGeckoResumeConfig,
    _parse_coin_ids,
    coingecko_source,
    start_date_error,
    validate_credentials as validate_coingecko_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    MAX_COINS,
    MERGE_ONLY_ENDPOINTS,
    PER_COIN_ENDPOINTS,
    PRO_ONLY_ENDPOINTS,
    SHOULD_SYNC_DEFAULT,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.coingecko import (
    CoinGeckoSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CoinGeckoSource(ResumableSource[CoinGeckoSourceConfig, CoinGeckoResumeConfig]):
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://docs.coingecko.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.COINGECKO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.COINGECKO,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="CoinGecko",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your CoinGecko API key to pull cryptocurrency market data into the PostHog Data warehouse.

Create a key in your [CoinGecko developer dashboard](https://www.coingecko.com/en/developers/dashboard). Free **Demo** keys (`x-cg-demo-api-key`) and paid **Pro** keys (`x-cg-pro-api-key`) use different hosts — pick the plan that matches your key.

CoinGecko enforces tight per-minute rate limits and monthly credit caps, especially on the Demo plan, so large tables may take a while to sync.

The market pairs, historical chart and OHLC tables are per coin, so they only sync once you list the coins you want.

The global market cap chart and NFT market tables need a Pro key on the Analyst plan or above.""",
            iconPath="/static/services/coingecko.png",
            docsUrl="https://posthog.com/docs/cdp/sources/coingecko",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="plan",
                        label="Plan",
                        required=True,
                        defaultValue=PLAN_DEMO,
                        options=[
                            SourceFieldSelectConfigOption(label="Demo (free)", value=PLAN_DEMO),
                            SourceFieldSelectConfigOption(label="Pro (paid)", value=PLAN_PRO),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="CG-...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="coin_ids",
                        label="Coin IDs",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="bitcoin, ethereum, solana",
                        secret=False,
                        caption=f"Comma-separated list of CoinGecko coin IDs, as they appear in the `coins_list` table. Up to {MAX_COINS} coins. The market pairs, historical chart and OHLC tables need this. The market-wide tables sync without it.",
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="2025-01-01",
                        secret=False,
                        caption="Earliest day of history to sync for the chart tables (YYYY-MM-DD). Defaults to one year ago, which is as far back as the Demo plan serves.",
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked key surfaces as a 401 when `_fetch` calls `raise_for_status()`.
            # Retrying can never fix a credential problem. Match the stable status text and base host,
            # not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.coingecko.com": "Your CoinGecko API key is invalid or has been revoked. Create a new Demo key in your CoinGecko dashboard, then reconnect.",
            "401 Client Error: Unauthorized for url: https://pro-api.coingecko.com": "Your CoinGecko Pro API key is invalid or has been revoked. Create a new Pro key in your CoinGecko dashboard, then reconnect.",
            NO_COINS_ERROR: "Add at least one coin ID in the source settings to sync this table.",
        }

    def get_schemas(
        self,
        config: CoinGeckoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        should_sync_default = dict(SHOULD_SYNC_DEFAULT)
        if config.plan != PLAN_PRO:
            # A Demo key is refused outright by the Pro-only endpoints, so one-shot setup must not
            # enable a table that can only 401.
            should_sync_default.update(dict.fromkeys(PRO_ONLY_ENDPOINTS, False))

        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            merge_only=MERGE_ONLY_ENDPOINTS,
            should_sync_default=should_sync_default,
        )

    def validate_credentials(
        self,
        config: CoinGeckoSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        coins = _parse_coin_ids(config.coin_ids)
        if len(coins) > MAX_COINS:
            return False, f"Too many coin IDs. List at most {MAX_COINS}."

        error = start_date_error(config.start_date)
        if error is not None:
            return False, error

        # Coin IDs are only checked per schema: the market-wide tables sync without them, so a
        # source that syncs only those must still connect.
        if not coins and schema_name in PER_COIN_ENDPOINTS:
            return False, "Add at least one coin ID to sync this table."

        if config.plan != PLAN_PRO and schema_name in PRO_ONLY_ENDPOINTS:
            return False, "This table needs a CoinGecko Pro key on the Analyst plan or above."

        if validate_coingecko_credentials(config.plan, config.api_key):
            return True, None

        # The probe also returns False on transient network/timeout errors, so don't claim the key is
        # definitively invalid — point at both possibilities.
        return (
            False,
            "Unable to verify your CoinGecko API key. Check that the key is correct and that CoinGecko is reachable.",
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CoinGeckoResumeConfig]:
        return ResumableSourceManager[CoinGeckoResumeConfig](inputs, CoinGeckoResumeConfig)

    def source_for_pipeline(
        self,
        config: CoinGeckoSourceConfig,
        resumable_source_manager: ResumableSourceManager[CoinGeckoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return coingecko_source(
            plan=config.plan,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            coin_ids=config.coin_ids,
            start_date=config.start_date,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
