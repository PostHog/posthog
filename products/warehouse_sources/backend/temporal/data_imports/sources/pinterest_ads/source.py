from typing import Optional, cast

import requests

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldOauthAccountSelectConfig,
    SourceFieldOauthConfig,
    SuggestedTable,
)

from posthog.exceptions_capture import capture_exception
from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, OauthIntegration

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP,
    FieldType,
    ResumableSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccount,
    IntegrationAccountListingError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PinterestAdsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.pinterest_ads import (
    PinterestAdsResumeConfig,
    pinterest_ads_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.settings import PINTEREST_ADS_CONFIG
from products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.utils import (
    build_session,
    list_ad_accounts,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _format_permission(permission: str) -> str:
    """Render Pinterest's screaming-snake permission enum as a badge label (``CAMPAIGN_MANAGER`` ->
    ``Campaign manager``)."""
    return permission.replace("_", " ").capitalize()


@SourceRegistry.register
class PinterestAdsSource(ResumableSource[PinterestAdsSourceConfig, PinterestAdsResumeConfig], OAuthMixin):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PINTERESTADS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "400 Client Error": "Pinterest Ads request failed. Please check your configuration.",
            "401 Client Error": "Pinterest Ads authentication failed. Please reconnect your Pinterest account.",
            "403 Client Error": "Pinterest Ads access forbidden. Please check your account permissions.",
            "404 Client Error": "Pinterest Ads resource not found. Please check your ad account ID.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PINTEREST_ADS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Pinterest Ads",
            caption="Collect campaign data, ad performance, and advertising metrics from Pinterest Ads. Ensure you have granted PostHog access to your Pinterest Ads account, learn how to do this in [the documentation](https://posthog.com/docs/cdp/sources/pinterest-ads).",
            releaseStatus=ReleaseStatus.GA,
            iconPath="/static/services/pinterest_ads.png",
            docsUrl="https://posthog.com/docs/cdp/sources/pinterest-ads",
            fields=cast(
                list[FieldType],
                [
                    # OAuth first: the account dropdown below is populated from this integration.
                    SourceFieldOauthConfig(
                        name="pinterest_ads_integration_id",
                        label="Pinterest Ads account",
                        required=True,
                        kind="pinterest-ads",
                    ),
                    SourceFieldOauthAccountSelectConfig(
                        name="ad_account_id",
                        label="Pinterest Ads Ad Account ID",
                        integrationField="pinterest_ads_integration_id",
                        integrationKind="pinterest-ads",
                        required=True,
                        placeholder="Your Pinterest Ads ad account ID",
                    ),
                ],
            ),
            suggestedTables=[
                SuggestedTable(
                    table="campaigns",
                    tooltip=MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP,
                ),
                SuggestedTable(
                    table="campaign_analytics",
                    tooltip=MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP,
                ),
            ],
        )

    def get_oauth_accounts(self, integration_id: int, team_id: int) -> list[IntegrationAccount]:
        try:
            integration = self.get_oauth_integration(integration_id, team_id)
        except ValueError as e:
            raise IntegrationAccountListingError(
                "The linked Pinterest Ads integration could not be found. "
                "Please reconnect your Pinterest Ads integration."
            ) from e

        oauth = OauthIntegration(integration)
        if integration.errors != ERROR_TOKEN_REFRESH_FAILED and oauth.access_token_expired():
            oauth.refresh_access_token()
        if integration.errors == ERROR_TOKEN_REFRESH_FAILED or not integration.access_token:
            raise IntegrationAccountListingError(
                "Could not refresh the Pinterest Ads credentials. Please reconnect your Pinterest Ads integration."
            )

        try:
            accounts = list_ad_accounts(build_session(integration.access_token))
        except requests.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else None
            if status_code not in (401, 403):
                # Any other status is a bug in the request we build, not something the user can fix.
                raise
            raise IntegrationAccountListingError(
                "Pinterest rejected the credentials for this integration. Please reconnect your Pinterest Ads "
                "integration and make sure the connected account can access your ad accounts."
            ) from e

        return [
            IntegrationAccount(
                value=account["id"],
                display_name=account.get("name") or "Unnamed account",
                badges=tuple(_format_permission(p) for p in account.get("permissions") or []),
            )
            for account in accounts
        ]

    def validate_credentials(
        self, config: PinterestAdsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if not config.ad_account_id or not config.pinterest_ads_integration_id:
            return False, "Ad Account ID and Pinterest Ads integration are required"

        try:
            self.get_oauth_integration(config.pinterest_ads_integration_id, team_id)
            return True, None
        except Exception as e:
            capture_exception(e)
            return False, f"Failed to validate Pinterest Ads credentials: {str(e)}"

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: PinterestAdsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint_config.name,
                supports_incremental=endpoint_config.incremental_fields is not None,
                supports_append=False,
                incremental_fields=endpoint_config.incremental_fields or [],
            )
            for endpoint_config in PINTEREST_ADS_CONFIG.values()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PinterestAdsResumeConfig]:
        return ResumableSourceManager[PinterestAdsResumeConfig](inputs, PinterestAdsResumeConfig)

    def source_for_pipeline(
        self,
        config: PinterestAdsSourceConfig,
        resumable_source_manager: ResumableSourceManager[PinterestAdsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        integration = self.get_oauth_integration(config.pinterest_ads_integration_id, inputs.team_id)

        if not integration.access_token:
            raise ValueError(f"Pinterest Ads access token not found for job {inputs.job_id}")

        return pinterest_ads_source(
            ad_account_id=config.ad_account_id,
            endpoint=inputs.schema_name,
            access_token=integration.access_token,
            resumable_source_manager=resumable_source_manager,
            source_logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
