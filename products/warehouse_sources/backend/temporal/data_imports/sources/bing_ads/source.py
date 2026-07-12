from typing import Optional, cast

from django.conf import settings

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldOauthAccountSelectConfig,
    SourceFieldOauthConfig,
    SuggestedTable,
)

from posthog.exceptions_capture import capture_exception

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BingAdsSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

from .bing_ads import bing_ads_source, get_incremental_fields, get_schemas
from .client import BingAdsClient
from .utils import BingAdsResumeConfig


@SourceRegistry.register
class BingAdsSource(ResumableSource[BingAdsSourceConfig, BingAdsResumeConfig], OAuthMixin):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BINGADS

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Match only on auth/permission failures that retrying cannot recover from.
        # Transient SDK errors (network, Bing outage, rate limits) propagate as their
        # original exception class and stay retryable — see BingAdsClient.get_customer_id,
        # which wraps the underlying error as `ValueError("Failed to fetch customer ID: <ExcType>: <msg>")`.
        auth_friendly = (
            "PostHog could not authenticate with Bing Ads. The connected account's OAuth credentials "
            "are revoked, expired, or no longer have access. Please reconnect your Bing Ads integration."
        )
        # Specific Azure AD error code surfaced when the tenant lacks a service principal for the
        # Microsoft Advertising API application. Reconnecting won't help — the org admin has to consent
        # on behalf of the tenant — so the generic "reconnect your integration" message is misleading.
        # Must be matched first: the SDK wraps this as `OAuthTokenRequestException: invalid_client AADSTS650052: …`,
        # so both "OAuthTokenRequestException" and "invalid_client" are substrings of the same message —
        # handle_non_retryable picks the first matching dict entry, so AADSTS650052 has to come before both.
        service_principal_friendly = (
            "Your Microsoft tenant has not consented to PostHog's Bing Ads connector "
            "(error AADSTS650052: missing service principal for the Microsoft Advertising API). "
            "Ask a Microsoft 365 administrator to grant admin consent to the application for your tenant, "
            "then reconnect your Bing Ads integration."
        )
        return {
            "AADSTS650052": service_principal_friendly,
            # OAuth grant rejection by Microsoft (the bingads SDK raises OAuthTokenRequestException
            # whose str() format is "<error_code> <error_description>").
            "OAuthTokenRequestException": auth_friendly,
            "invalid_grant": auth_friendly,
            "invalid_client": auth_friendly,
            "unauthorized_client": auth_friendly,
            # Bing Ads service-level auth error codes surfaced via suds.WebFault details
            # (see BingAdsClient.get_customer_id / extract_webfault_detail).
            "AuthenticationTokenExpired": auth_friendly,
            "AuthenticationFailed": auth_friendly,
            "InvalidCredentials": auth_friendly,
            "OAuthTokenExpired": auth_friendly,
            # Bing returns the generic SOAP fault "Invalid client data. Check the SOAP fault details for
            # more information. TrackingId: <uuid>." for two distinct deterministic conditions, neither of
            # which retrying can recover:
            #   - the request is rejected as invalid *after* auth succeeds — the configured Account ID is
            #     wrong, or the connected Microsoft Advertising user can't access it — raised by the SDK as
            #     `suds.WebFault("Server raised fault: 'Invalid client data...'")`;
            #   - CustomerManagementService.GetUser can't use the connected account (revoked/expired
            #     credentials, a work/school identity instead of a personal Microsoft account —
            #     WorkIdentityNotAvailable — or no access). GetUser takes no request parameters, so this is
            #     never a malformed-request bug on our side.
            # Match the stable phrase only; the TrackingId is volatile. This does not catch transient Bing
            # faults like "Server raised fault: 'Internal Error'".
            "Invalid client data": (
                "PostHog could not use the connected Bing Ads account (Microsoft returned 'Invalid client data'). "
                "This usually means the configured Account ID is incorrect, the connected account's credentials are "
                "no longer valid, or it does not have access to the Microsoft Advertising account. Please check the "
                "Account ID in your source settings and reconnect your Bing Ads integration, making sure the "
                "signed-in account can access the account in Microsoft Advertising."
            ),
            # Integration row was deleted/disconnected while a scheduled job still references it.
            # Raised by OAuthMixin.get_oauth_integration as `ValueError("Integration not found: <id>")`;
            # the id is volatile, so match only the stable prefix. Retrying can't recreate the row —
            # the customer has to reconnect.
            "Integration not found": "The linked Bing Ads integration no longer exists. Please reconnect your Bing Ads integration.",
            # Non-numeric Account ID — the user entered their alphanumeric Account Number instead
            # of the numeric Account ID. Retrying can't fix a bad config value, so flag it and surface
            # actionable guidance. The matched phrase is stable and precedes the volatile id in the
            # raised message (see bing_ads_source.get_rows), keeping false positives at zero.
            "Bing Ads Account ID must be numeric": (
                "Bing Ads Account ID must be numeric. You may have entered your alphanumeric Account Number "
                "instead. Update the Account ID in the source settings and try again."
            ),
            # Deterministic credential/config errors raised in source_for_pipeline.
            "Bing Ads access token not found": "Bing Ads OAuth access token is missing. Please reconnect your Bing Ads integration.",
            "Bing Ads refresh token not found": "Bing Ads OAuth refresh token is missing. Please reconnect your Bing Ads integration.",
            "Bing Ads developer token not configured": None,
            # PostHog's Bing Ads OAuth application credentials aren't configured — an empty client_id makes
            # Microsoft reject the token request with AADSTS900144. Internal config, not customer-actionable.
            "Bing Ads OAuth application credentials not configured": None,
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BING_ADS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            keywords=["microsoft ads", "microsoft advertising"],
            label="Bing Ads",
            caption="Ensure you have granted PostHog access to your Bing Ads account, learn how to do this in [the documentation](https://posthog.com/docs/cdp/sources/bing-ads).",
            releaseStatus="beta",
            iconPath="/static/services/bing-ads.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/bing-ads",
            fields=cast(
                list[FieldType],
                [
                    # OAuth first: the account dropdown below is populated from this integration.
                    SourceFieldOauthConfig(
                        name="bing_ads_integration_id",
                        label="Bing Ads account",
                        required=True,
                        kind="bing-ads",
                    ),
                    SourceFieldOauthAccountSelectConfig(
                        name="account_id",
                        label="Account ID",
                        integrationField="bing_ads_integration_id",
                        integrationKind="bing-ads",
                        required=True,
                    ),
                ],
            ),
            suggestedTables=[
                SuggestedTable(
                    table="campaigns",
                    tooltip=MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP,
                ),
                SuggestedTable(
                    table="campaign_performance_report",
                    tooltip=MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP,
                ),
            ],
        )

    def validate_credentials(
        self, config: BingAdsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if not config.account_id or not config.bing_ads_integration_id:
            return False, "Account ID and Bing Ads integration are required"

        if not config.account_id.isdigit():
            return (
                False,
                f"Invalid Account ID '{config.account_id}'. Bing Ads Account IDs are numeric. You can find your Account ID in the Bing Ads dashboard under Settings > Account.",
            )

        try:
            self.get_oauth_integration(config.bing_ads_integration_id, team_id)
            return True, None
        except Exception as e:
            if isinstance(e, ValueError) and "Integration not found" in str(e):
                # The integration was deleted/disconnected while the source still references it —
                # an expected user state, not an error worth reporting (get_oauth_integration raises
                # ValueError("Integration not found: <id>")).
                return False, "Bing Ads integration not found. Please reconnect your Bing Ads integration."
            capture_exception(e)
            return False, f"Failed to validate Bing Ads credentials: {str(e)}"

    def _actionable_listing_message(self, error: str) -> str | None:
        """Map a wrapped list_accounts error to the friendly, customer-actionable message for it, or
        None if it isn't a known auth/credential failure (so it stays a 500). Reuses the non-retryable
        catalog — entries with a None friendly message are internal config issues, not user-actionable."""
        for substring, friendly in self.get_non_retryable_errors().items():
            if friendly is not None and substring in error:
                return friendly
        return None

    def get_oauth_accounts(self, integration_id: int, team_id: int) -> list[IntegrationAccount]:
        try:
            integration = self.get_oauth_integration(integration_id, team_id)
        except ValueError as e:
            # get_oauth_integration raises ValueError for a missing/foreign integration id — an
            # actionable customer-side state (deleted/disconnected), not a server bug.
            raise IntegrationAccountListingError(
                "The linked Bing Ads integration could not be found. Please reconnect your Bing Ads integration."
            ) from e

        if not settings.BING_ADS_DEVELOPER_TOKEN:
            raise ValueError("Bing Ads developer token not configured")
        if not integration.access_token:
            raise IntegrationAccountListingError(
                "Bing Ads access token not found. Please reconnect your Bing Ads integration."
            )
        if not integration.refresh_token:
            raise IntegrationAccountListingError(
                "Bing Ads refresh token not found. Please reconnect your Bing Ads integration."
            )

        client = BingAdsClient(
            access_token=integration.access_token,
            refresh_token=integration.refresh_token,
            developer_token=settings.BING_ADS_DEVELOPER_TOKEN,
        )
        try:
            return client.list_accounts()
        except ValueError as e:
            # list_accounts funnels SDK errors through _wrap_with_fault_detail, which preserves the
            # underlying type/message inside a ValueError. Match the known auth/credential failures
            # (same substrings the retry classifier uses) and surface them as an actionable 400; let
            # anything else propagate as a 500 so genuine bugs aren't masked as bad user input.
            friendly = self._actionable_listing_message(str(e))
            if friendly is not None:
                raise IntegrationAccountListingError(friendly) from e
            raise

    def get_schemas(
        self,
        config: BingAdsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        bing_ads_schemas = get_schemas()
        ads_incremental_fields = get_incremental_fields()

        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=ads_incremental_fields.get(endpoint, None) is not None,
                supports_append=ads_incremental_fields.get(endpoint, None) is not None,
                incremental_fields=[
                    {"label": column_name, "type": column_type, "field": column_name, "field_type": column_type}
                    for column_name, column_type in ads_incremental_fields.get(endpoint, [])
                ],
            )
            for endpoint in bing_ads_schemas.keys()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BingAdsResumeConfig]:
        return ResumableSourceManager[BingAdsResumeConfig](inputs, BingAdsResumeConfig)

    def source_for_pipeline(
        self,
        config: BingAdsSourceConfig,
        resumable_source_manager: ResumableSourceManager[BingAdsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        integration = self.get_oauth_integration(config.bing_ads_integration_id, inputs.team_id)

        if not integration.access_token:
            raise ValueError(f"Bing Ads access token not found for job {inputs.job_id}")
        if not integration.refresh_token:
            raise ValueError(f"Bing Ads refresh token not found for job {inputs.job_id}")

        return bing_ads_source(
            account_id=config.account_id,
            resource_name=inputs.schema_name,
            access_token=integration.access_token,
            refresh_token=integration.refresh_token,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field if inputs.should_use_incremental_field else None,
            incremental_field_type=inputs.incremental_field_type if inputs.should_use_incremental_field else None,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
