from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.coingecko import (
    PLAN_DEMO,
    PLAN_PRO,
    CoinGeckoResumeConfig,
    coingecko_source,
    validate_credentials as validate_coingecko_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.settings import (
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CoinGeckoSourceConfig
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
            name=SchemaExternalDataSourceType.COIN_GECKO,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="CoinGecko",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your CoinGecko API key to pull cryptocurrency market data into the PostHog Data warehouse.

Create a key in your [CoinGecko developer dashboard](https://www.coingecko.com/en/developers/dashboard). Free **Demo** keys (`x-cg-demo-api-key`) and paid **Pro** keys (`x-cg-pro-api-key`) use different hosts — pick the plan that matches your key.

CoinGecko enforces tight per-minute rate limits and monthly credit caps, especially on the Demo plan, so large tables may take a while to sync.""",
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
        }

    def get_schemas(
        self,
        config: CoinGeckoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every exposed endpoint is a catalog/snapshot with no server-side timestamp filter, so all
        # are full refresh only (no incremental/append).
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: CoinGeckoSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
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
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
