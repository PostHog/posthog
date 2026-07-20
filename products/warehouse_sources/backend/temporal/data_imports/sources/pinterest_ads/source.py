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
    return permission.replace("_", " ").capitalize()


@SourceRegistry.register
class PinterestAdsSource(ResumableSource[PinterestAdsSourceConfig, PinterestAdsResumeConfig], OAuthMixin):
    supported_versions = ("v5",)
    default_version = "v5"
    api_docs_url = "https://developers.pinterest.com/docs/api/v5/"

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

    def get_expected_transient_errors(self) -> list[str]:
        # Pinterest's API intermittently returns server-side 5xx (mostly 500, some 503) on the
        # entity and analytics endpoints. The tracked session already retries these, and Temporal
        # retries the whole activity, so a persistent 5xx is expected upstream flakiness rather than
        # a bug in our code. Classify it as transient so it is logged at warning level instead of
        # opening a fresh error-tracking issue on every retry.
        return [
            "500 Server Error",
            "502 Server Error",
            "503 Server Error",
            "504 Server Error",
        ]

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

    def get_oauth_accounts(
        self, integration_id: int, team_id: int, search: str | None = None
    ) -> list[IntegrationAccount]:
        # A user's ad accounts are few, so `search` is ignored here and the endpoint filters the list.
        try:
            integration = self.get_oauth_integration(integration_id, team_id)
        except ValueError as e:
            raise IntegrationAccountListingError(
                "The linked Pinterest Ads integration could not be found. "
                "Please reconnect your Pinterest Ads integration."
            ) from e

        oauth = OauthIntegration(integration)
        if oauth.access_token_expired():
            try:
                oauth.refresh_access_token()
            except (requests.RequestException, ValueError) as e:
                # `refresh_access_token` only records failure in `integration.errors` when Pinterest
                # answers with a parseable body. A network error, or an HTML error page it then fails
                # to `.json()`, escapes instead — transient either way, so don't let it 500.
                raise IntegrationAccountListingError(
                    "Could not reach Pinterest to refresh the credentials for this integration. "
                    "Please try again in a few minutes."
                ) from e
        if integration.errors == ERROR_TOKEN_REFRESH_FAILED or not integration.access_token:
            raise IntegrationAccountListingError(
                "Could not refresh the Pinterest Ads credentials. Please reconnect your Pinterest Ads integration."
            )

        try:
            accounts = list_ad_accounts(build_session(integration.access_token))
        except requests.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else None
            if status_code in (401, 403):
                raise IntegrationAccountListingError(
                    "Pinterest rejected the credentials for this integration. Please reconnect your Pinterest Ads "
                    "integration and make sure the connected account can access your ad accounts."
                ) from e
            if status_code == 429:
                # Pinterest rate-limits `/ad_accounts`, so this is neither a bug nor the user's fault.
                raise IntegrationAccountListingError(
                    "Pinterest is rate limiting this connection. Please wait a moment and try again."
                ) from e
            if status_code is not None and status_code >= 500:
                raise IntegrationAccountListingError(
                    "Pinterest is having trouble responding right now. Please try again in a few minutes."
                ) from e
            # Any other status means we built a bad request, which the user cannot fix.
            raise
        except requests.RequestException as e:
            # A connection error or read timeout that outlived the retry policy in `_make_request`
            # (it retries transport failures but reraises once attempts are exhausted). This is a
            # transient outage like a 5xx, not a bug, so surface the same actionable message instead
            # of letting a bare `RequestException` escape as a 500.
            raise IntegrationAccountListingError(
                "Pinterest is having trouble responding right now. Please try again in a few minutes."
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
