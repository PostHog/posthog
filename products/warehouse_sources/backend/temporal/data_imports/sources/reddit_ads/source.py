from typing import Optional, cast

from requests.exceptions import RequestException

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RedditAdsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.reddit_ads.reddit_ads import (
    RedditAdsApiError,
    RedditAdsResumeConfig,
    list_business_ad_accounts,
    list_businesses,
    reddit_ads_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.reddit_ads.settings import REDDIT_ADS_CONFIG
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RedditAdsSource(ResumableSource[RedditAdsSourceConfig, RedditAdsResumeConfig], OAuthMixin):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://ads-api.reddit.com/docs/v3/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.REDDITADS

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.reddit_ads.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": None,
            # Reddit returns 403 when the connected account lacks permission to read the
            # configured ad account's reports (access revoked or insufficient scope). The
            # request can never succeed without the user reconnecting, so stop retrying.
            "403 Client Error": "PostHog is not authorized to access this Reddit Ads account. Please make sure the connected Reddit account has access to the ad account, then reconnect.",
            "404 Client Error": None,
            # Raised by OAuthMixin.get_oauth_integration when the connected Reddit Ads
            # account has been deleted or disconnected. The integration row is gone, so
            # retrying can never recover it — stop and ask the user to reconnect.
            "Integration not found": "The connected Reddit Ads account is no longer available — it may have been disconnected. Please reconnect the source's account.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.REDDIT_ADS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Reddit Ads",
            caption="Collect campaign data, ad performance, and advertising metrics from Reddit Ads. Ensure you have granted PostHog access to your Reddit Ads account, learn how to do this in [the documentation](https://posthog.com/docs/cdp/sources/reddit-ads).",
            releaseStatus=ReleaseStatus.GA,
            iconPath="/static/services/reddit.png",
            docsUrl="https://posthog.com/docs/cdp/sources/reddit-ads",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="reddit_integration_id",
                        label="Reddit Ads account",
                        required=True,
                        kind="reddit-ads",
                    ),
                    SourceFieldOauthAccountSelectConfig(
                        name="account_id",
                        label="Reddit Ads Account ID",
                        integrationField="reddit_integration_id",
                        integrationKind="reddit-ads",
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
                    table="campaign_report",
                    tooltip=MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP,
                ),
            ],
        )

    def get_oauth_accounts(
        self, integration_id: int, team_id: int, search: str | None = None
    ) -> list[IntegrationAccount]:
        # A Reddit member's ad accounts are few, so `search` is ignored here and the endpoint filters the list.
        try:
            integration = self.get_oauth_integration(integration_id, team_id)
        except ValueError as e:
            raise IntegrationAccountListingError(
                "The linked Reddit Ads integration could not be found. Please reconnect your Reddit Ads integration."
            ) from e

        # `errors` persists on the row, so a past transient refresh failure must not stop us from
        # trying again — `refresh_access_token` clears it on entry and usually succeeds.
        oauth = OauthIntegration(integration)
        if oauth.access_token_expired():
            try:
                oauth.refresh_access_token()
            except RequestException as e:
                # A refresh that fails before Reddit returns an HTTP response (timeout, dropped
                # connection) never reaches the code that records ERROR_TOKEN_REFRESH_FAILED, so it
                # would escape as an unhandled 500. Map it to the same transient guidance the handled
                # failures return.
                raise IntegrationAccountListingError(
                    "Could not reach Reddit to refresh the credentials for this integration. Please try again."
                ) from e
        if integration.errors == ERROR_TOKEN_REFRESH_FAILED or not integration.access_token:
            raise IntegrationAccountListingError(
                "Could not refresh the Reddit Ads credentials. Please reconnect your Reddit Ads integration."
            )

        access_token = integration.access_token
        try:
            return [
                IntegrationAccount(
                    value=account["id"],
                    display_name=account.get("name") or "Unnamed account",
                    # Sources predating this picker were configured by typing the account id, and
                    # `group` is not searchable, so surface the id users already know.
                    secondary_text=account["id"],
                    badges=("Suspended",) if account.get("suspension_reason") else (),
                    group=business.get("name"),
                )
                for business in list_businesses(access_token)
                for account in list_business_ad_accounts(access_token, business["id"])
            ]
        except RedditAdsApiError as e:
            if e.api_status_code in (401, 403):
                raise IntegrationAccountListingError(
                    "Reddit rejected the credentials for this integration. Please reconnect your Reddit Ads "
                    "integration and make sure the connected account can access your ad accounts."
                ) from e
            if e.api_status_code == 429 or e.api_status_code >= 500:
                # The session already retried these; Reddit rate-limits ~1 req/s per advertiser and this
                # listing fires one call per business, so exhausting the retries is expected under load.
                raise IntegrationAccountListingError(
                    "Reddit is rate-limiting or temporarily unavailable for this integration. Please try again."
                ) from e
            # Any other status means we built a bad request, which the user cannot fix.
            raise

    def validate_credentials(
        self, config: RedditAdsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if not config.account_id or not config.reddit_integration_id:
            return False, "Account ID and Reddit Ads integration are required"

        try:
            self.get_oauth_integration(config.reddit_integration_id, team_id)
            return True, None
        except Exception as e:
            if isinstance(e, ValueError) and "Integration not found" in str(e):
                # The integration was deleted/disconnected while the source still references it —
                # an expected user state, not an error worth reporting (get_oauth_integration raises
                # ValueError("Integration not found: <id>")).
                return False, "Reddit Ads integration not found. Please reconnect your Reddit Ads integration."
            capture_exception(e)
            return False, f"Failed to validate Reddit Ads credentials: {str(e)}"

    def get_schemas(
        self,
        config: RedditAdsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=str(endpoint_config.resource["name"]),
                supports_incremental=endpoint_config.incremental_fields is not None,
                supports_append=False,
                incremental_fields=endpoint_config.incremental_fields or [],
            )
            for endpoint_config in REDDIT_ADS_CONFIG.values()
        ]

        if names:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RedditAdsResumeConfig]:
        return ResumableSourceManager[RedditAdsResumeConfig](inputs, RedditAdsResumeConfig)

    def source_for_pipeline(
        self,
        config: RedditAdsSourceConfig,
        resumable_source_manager: ResumableSourceManager[RedditAdsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        integration = self.get_oauth_integration(config.reddit_integration_id, inputs.team_id)

        if not integration.access_token:
            raise ValueError(f"Reddit Ads access token not found for job {inputs.job_id}")

        return reddit_ads_source(
            account_id=config.account_id,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            access_token=integration.access_token,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
