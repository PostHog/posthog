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
from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_ads.amazon_ads import (
    amazon_ads_source,
    validate_credentials as validate_amazon_ads_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_ads.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AmazonAdsSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AmazonAdsSource(SimpleSource[AmazonAdsSourceConfig]):
    api_docs_url = "https://advertising.amazon.com/API/docs"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AMAZONADS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "400 Client Error: Bad Request for url: https://api.amazon.com/auth/o2/token": "Amazon Ads authentication failed. Your refresh token may be invalid or revoked — please check your Login with Amazon credentials.",
            "401 Client Error: Unauthorized for url: https://api.amazon.com/auth/o2/token": "Amazon Ads authentication failed. Please check your Login with Amazon client ID and secret.",
            "403 Client Error: Forbidden for url: https://advertising-api": "Amazon Ads denied access. Please check that your Login with Amazon application has Advertising API access and the right region.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AMAZON_ADS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Amazon Ads",
            caption="""Connect your Amazon Ads account to pull your advertising entity data into the PostHog Data warehouse.

You need a Login with Amazon (LWA) application with Advertising API access: enter its client ID and secret plus a refresh token authorized for your advertiser account. Pick the region that matches your advertising profiles (North America, Europe, or Far East). Sponsored Products campaigns and ad groups are synced from every profile the token can access.""",
            iconPath="/static/services/amazon_ads.png",
            docsUrl="https://posthog.com/docs/cdp/sources/amazon-ads",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="na",
                        options=[
                            SourceFieldSelectConfigOption(label="North America", value="na"),
                            SourceFieldSelectConfigOption(label="Europe", value="eu"),
                            SourceFieldSelectConfigOption(label="Far East", value="fe"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="client_id",
                        label="LWA client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="amzn1.application-oa2-client...",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="LWA client secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="refresh_token",
                        label="Refresh token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Atzr|...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_ads.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AmazonAdsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Entity lists have no updated-since filter; performance metrics ship
        # via the async reporting API (a follow-up).
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: AmazonAdsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_amazon_ads_credentials(config.region, config.client_id, config.client_secret, config.refresh_token):
            return True, None

        return False, "Invalid Amazon Ads credentials"

    def source_for_pipeline(self, config: AmazonAdsSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return amazon_ads_source(
            region=config.region,
            client_id=config.client_id,
            client_secret=config.client_secret,
            refresh_token=config.refresh_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
