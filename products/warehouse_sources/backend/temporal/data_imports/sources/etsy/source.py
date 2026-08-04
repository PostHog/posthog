from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.etsy.etsy import (
    EtsyResumeConfig,
    etsy_source,
    validate_credentials as validate_etsy_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.etsy.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.etsy import EtsySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class EtsySource(ResumableSource[EtsySourceConfig, EtsyResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://developers.etsy.com/documentation/reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ETSY

    @property
    def connection_host_fields(self) -> list[str]:
        # shop_id steers where the stored token is sent (/shops/{shop_id}), so retargeting it must
        # force the editor to re-enter the credentials rather than reuse the preserved ones.
        return ["shop_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ETSY,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Etsy",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["etsy", "receipts", "orders", "marketplace"],
            caption="""Sync your Etsy shop's orders, listings, reviews and payment ledger into the PostHog Data warehouse.

Register a personal app in the [Etsy developer portal](https://www.etsy.com/developers/your-apps) to get a keystring, then run Etsy's OAuth flow to grant your shop and keep the refresh token it returns. The token needs the `transactions_r`, `listings_r` and `shops_r` scopes — add `billing_r` if you want the payment ledger. Leave the shop ID blank and we'll use the shop the token belongs to.""",
            iconPath="/static/services/etsy.png",
            docsUrl="https://posthog.com/docs/cdp/sources/etsy",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API keystring",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Your app's keystring",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="refresh_token",
                        label="Refresh token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="shop_id",
                        label="Shop ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="Leave blank to use the token's own shop",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.etsy.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Etsy answers a revoked or expired refresh token with a 400 from the token endpoint.
            # Refresh tokens last 90 days, so this is the expected end-of-life failure.
            "400 Client Error: Bad Request for url: https://api.etsy.com/v3/public/oauth/token": "Your Etsy refresh token is expired or revoked. Etsy refresh tokens last 90 days — reauthorize the app and paste the new token.",
            "401 Client Error: Unauthorized for url: https://api.etsy.com": "Etsy rejected your credentials. Check the API keystring and refresh token, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.etsy.com": "Your Etsy token is missing a scope this table needs (transactions_r, listings_r, shops_r or billing_r). Reauthorize with the scopes you want to sync.",
            "This Etsy account has no shop": "The connected Etsy account does not own a shop. Enter the shop ID you want to sync, or reconnect with the seller account.",
        }

    def get_schemas(
        self,
        config: EtsySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: EtsySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_etsy_credentials(config.api_key, config.refresh_token, config.shop_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[EtsyResumeConfig]:
        return ResumableSourceManager[EtsyResumeConfig](inputs, EtsyResumeConfig)

    def source_for_pipeline(
        self,
        config: EtsySourceConfig,
        resumable_source_manager: ResumableSourceManager[EtsyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return etsy_source(
            api_key=config.api_key,
            refresh_token=config.refresh_token,
            shop_id=config.shop_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
