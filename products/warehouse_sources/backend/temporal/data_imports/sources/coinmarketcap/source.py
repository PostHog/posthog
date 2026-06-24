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
from products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.coinmarketcap import (
    CoinMarketCapResumeConfig,
    coinmarketcap_source,
    validate_credentials as validate_coinmarketcap_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.settings import (
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CoinMarketCapSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CoinMarketCapSource(ResumableSource[CoinMarketCapSourceConfig, CoinMarketCapResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.COINMARKETCAP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.COIN_MARKET_CAP,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="CoinMarketCap",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your CoinMarketCap Pro API key to sync cryptocurrency and market data into the PostHog Data warehouse.

Create a key from your [CoinMarketCap developer dashboard](https://pro.coinmarketcap.com/account). The key grants read access to every endpoint listed below; some (e.g. exchanges) require a higher plan tier.""",
            iconPath="/static/services/coinmarketcap.png",
            docsUrl="https://posthog.com/docs/cdp/sources/coinmarketcap",
            # Kept hidden from the new-source wizard for now; flip this off to release.
            unreleasedSource=True,
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
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A missing or invalid Pro API key surfaces as a 401 when the pipeline calls
            # `raise_for_status()`. Retrying can never satisfy a credential problem.
            "401 Client Error": "Your CoinMarketCap API key is invalid or has been revoked. Create a new key in your CoinMarketCap developer dashboard, then reconnect.",
            "Unauthorized for url": "Your CoinMarketCap API key is invalid or has been revoked. Create a new key in your CoinMarketCap developer dashboard, then reconnect.",
        }

    def get_schemas(
        self,
        config: CoinMarketCapSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=(fields := INCREMENTAL_FIELDS.get(endpoint)) is not None,
                supports_append=fields is not None,
                incremental_fields=fields or [],
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: CoinMarketCapSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_coinmarketcap_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CoinMarketCapResumeConfig]:
        return ResumableSourceManager[CoinMarketCapResumeConfig](inputs, CoinMarketCapResumeConfig)

    def source_for_pipeline(
        self,
        config: CoinMarketCapSourceConfig,
        resumable_source_manager: ResumableSourceManager[CoinMarketCapResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return coinmarketcap_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
