from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_selling_partner.amazon_selling_partner import (
    MISSING_MARKETPLACES_MESSAGE,
    AmazonSellingPartnerResumeConfig,
    amazon_selling_partner_source,
    parse_marketplace_ids,
    probe_endpoint_permissions,
    validate_credentials as validate_amazon_selling_partner_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_selling_partner.settings import (
    DEFAULT_INCREMENTAL_LOOKBACK_SECONDS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAUTH2_PERMANENT_ERROR_MARKER,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.amazonsellingpartner import (
    AmazonSellingPartnerSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AmazonSellingPartnerSource(ResumableSource[AmazonSellingPartnerSourceConfig, AmazonSellingPartnerResumeConfig]):
    codebase_detection = detect(
        env=("^SP_API_",),
        npm=("amazon-sp-api", "@sp-api-sdk/orders-api-v0", "@sp-api-sdk/auth"),
        pypi=("python-amazon-sp-api",),
        rubygems=("amz_sp_api",),
        composer=("jlevers/selling-partner-api", "highsidelabs/laravel-spapi"),
        go=("github.com/amzapi/selling-partner-api-sdk",),
    )
    # The refresh token comes from a seller-side authorization flow, so users set this up in the app.
    setup_requires_ui = True

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # Each SP-API section carries its own dated version, so there is no single pin for the source.
    api_docs_url = "https://developer-docs.amazon.com/sp-api/changelog"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AMAZONSELLINGPARTNER

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "HTTP 400 from the OAuth2 token endpoint": "Amazon rejected the refresh token. Re-authorize the app for this seller and update the refresh token.",
            "HTTP 401 from the OAuth2 token endpoint": "Amazon rejected the Login with Amazon client ID or client secret. Check them in the Amazon developer console and update the source.",
            "401 Client Error: Unauthorized for url: https://sellingpartnerapi": "Amazon rejected the access token. Re-authorize the app for this seller and update the refresh token.",
            "403 Client Error: Forbidden for url: https://sellingpartnerapi": "Amazon refused access to this table. Check that the app has the role the table needs and that the account authorized it.",
            MISSING_MARKETPLACES_MESSAGE: MISSING_MARKETPLACES_MESSAGE,
            "Unknown Amazon marketplace ID for real-time sales": "A marketplace ID in the source settings is not one Amazon lists. Check the IDs and update the source.",
            OAUTH2_PERMANENT_ERROR_MARKER: "Amazon rejected the Login with Amazon credentials. Check the client ID, client secret and refresh token, then update the source.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_selling_partner.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AmazonSellingPartnerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            default_incremental_lookback_seconds=DEFAULT_INCREMENTAL_LOOKBACK_SECONDS,
        )

    def validate_credentials(
        self,
        config: AmazonSellingPartnerSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_amazon_selling_partner_credentials(
            config.region,
            config.client_id,
            config.client_secret,
            config.refresh_token,
            parse_marketplace_ids(config.marketplace_ids),
        )

    def get_endpoint_permissions(
        self,
        config: AmazonSellingPartnerSourceConfig,
        team_id: int,
        endpoints: list[str],
        api_version: str | None = None,
    ) -> dict[str, str | None]:
        return probe_endpoint_permissions(
            config.region,
            config.client_id,
            config.client_secret,
            config.refresh_token,
            parse_marketplace_ids(config.marketplace_ids),
            endpoints,
        )

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[AmazonSellingPartnerResumeConfig]:
        return ResumableSourceManager[AmazonSellingPartnerResumeConfig](inputs, AmazonSellingPartnerResumeConfig)

    def source_for_pipeline(
        self,
        config: AmazonSellingPartnerSourceConfig,
        resumable_source_manager: ResumableSourceManager[AmazonSellingPartnerResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return amazon_selling_partner_source(
            region=config.region,
            client_id=config.client_id,
            client_secret=config.client_secret,
            refresh_token=config.refresh_token,
            marketplace_ids=parse_marketplace_ids(config.marketplace_ids),
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AMAZONSELLINGPARTNER,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Amazon Selling Partner",
            keywords=["sp-api", "seller central", "vendor central", "amazon seller", "amazon vendor", "fba"],
            caption=(
                "Seller accounts sync orders, order items, financial transactions and FBA inventory. "
                "The app needs the Inventory and Order Tracking, Finance and Accounting and Amazon Fulfillment roles. "
                "Orders and order items read the same Amazon endpoint, so syncing both takes twice as long. "
                "Vendor accounts sync daily sales, inventory, net pure product margin, forecasts and hourly sales "
                "reports, which need the Brand Analytics role and your marketplace IDs."
            ),
            iconPath="/static/services/amazon_selling_partner.png",
            docsUrl="https://posthog.com/docs/cdp/sources/amazon-selling-partner",
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
                    SourceFieldInputConfig(
                        name="marketplace_ids",
                        label="Marketplace IDs",
                        caption="Comma-separated. Required for vendor reports. For sellers it applies to orders, order items and inventory, while transactions always cover every marketplace. Sellers can leave it blank to use every marketplace they sell in.",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="ATVPDKIKX0DER, A1F83G8C2ARO7P",
                        secret=False,
                    ),
                ],
            ),
        )
