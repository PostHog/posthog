from typing import Optional, cast

import requests

from products.warehouse_sources.sources.google_admob._config import GoogleAdMobSourceConfig
from products.warehouse_sources.sources.google_admob.google_admob import (
    AdMobAuthError,
    AdMobClient,
    AdMobResumeConfig,
    google_admob_source,
    validate_credentials as validate_admob_credentials,
)
from products.warehouse_sources.sources.google_admob.settings import (
    ADMOB_LISTS,
    ADMOB_REPORTS,
    DATE_INCREMENTAL_FIELDS,
    REQUIRED_SCOPES,
    REVISION_LOOKBACK_SECONDS,
)
from products.warehouse_sources.sources.sdk import (
    ERROR_TOKEN_REFRESH_FAILED,
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    IntegrationAccount,
    IntegrationAccountListingError,
    OauthIntegration,
    OAuthMixin,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    RetryableHTTPError,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthAccountSelectConfig,
    SourceFieldOauthConfig,
    SourceInputs,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    detect,
)

INTEGRATION_KIND = "google-admob"

RECONNECT_MESSAGE = "Could not use the credentials for this AdMob connection. Please reconnect the Google account."


class AdMobTokenRefreshError(Exception):
    """Google's token endpoint failed for a reason that can pass, such as a timeout or a 5xx."""


@SourceRegistry.register
class GoogleAdMobSource(ResumableSource[GoogleAdMobSourceConfig, AdMobResumeConfig], OAuthMixin):
    codebase_detection = detect(
        npm=("react-native-google-mobile-ads", "@capacitor-community/admob", "@react-native-firebase/admob"),
        pub=("google_mobile_ads",),
        cocoapods=("Google-Mobile-Ads-SDK",),
        maven=("com.google.android.gms:play-services-ads", "com.google.android.gms:play-services-ads-lite"),
        swiftpm=("github.com/googleads/swift-package-manager-google-mobile-ads",),
    )

    api_docs_url = "https://developers.google.com/admob/api/release-notes"
    # v1beta adds more resources, but it is a beta channel, so the source pins the GA v1.
    supported_versions = ("v1",)
    default_version = "v1"

    lists_tables_without_credentials = True  # static report and list catalog

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEADMOB

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Google rejected the credentials for this connection. Please reconnect the Google account.",
            "403 Client Error: Forbidden for url: https://admob.googleapis.com": (
                "The connected Google account cannot read this AdMob account. Reconnect with a Google account "
                "that has access to it, and grant the AdMob permission."
            ),
            "404 Client Error: Not Found for url: https://admob.googleapis.com": (
                "AdMob could not find this account. Pick an account the connected Google account has access to."
            ),
            "Integration not found": "The Google account for this source is no longer connected. Please reconnect it.",
            # Already the actionable message, so keep it rather than substituting another.
            RECONNECT_MESSAGE: None,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.google_admob.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def access_token(self, integration_id: int, team_id: int, force_refresh: bool = False) -> str:
        """A valid Google access token for the linked account. `force_refresh` mints a new one even
        when the current one looks fresh, for a token that Google rejected mid-sync."""
        integration = self.get_oauth_integration(integration_id, team_id)
        # The lookup only scopes to the team, so a config pointing at another provider's integration
        # would otherwise send that provider's token to Google, and refresh it on a 401.
        if integration.kind != INTEGRATION_KIND:
            raise ValueError(f"Integration not found: {integration_id}")

        oauth = OauthIntegration(integration)
        if force_refresh or oauth.access_token_expired():
            integration = oauth.refresh_access_token()
            if integration.errors == ERROR_TOKEN_REFRESH_FAILED:
                # Only a dead grant marks the row terminal. A timeout or a 5xx from Google's token
                # endpoint can pass, so the sync retries instead of asking the user to reconnect.
                if integration.config.get("refresh_terminal"):
                    raise AdMobAuthError(RECONNECT_MESSAGE)
                raise AdMobTokenRefreshError(
                    "Could not refresh the Google access token for this AdMob connection. The sync will retry."
                )

        if not integration.access_token:
            raise AdMobAuthError(RECONNECT_MESSAGE)

        return integration.access_token

    def get_oauth_accounts(
        self, integration_id: int, team_id: int, search: str | None = None
    ) -> list[IntegrationAccount]:
        # A Google account has access to one AdMob account, so `search` is ignored and the endpoint
        # filters the returned list.
        try:
            access_token = self.access_token(integration_id, team_id)
        except ValueError as e:
            raise IntegrationAccountListingError(
                "The Google account for this source is no longer connected. Please reconnect it."
            ) from e
        except AdMobAuthError as e:
            raise IntegrationAccountListingError(str(e)) from e
        except (AdMobTokenRefreshError, requests.RequestException) as e:
            raise IntegrationAccountListingError(
                "Could not reach Google to refresh this connection. Please try again in a few minutes."
            ) from e

        try:
            accounts = AdMobClient(access_token, retry=False).list_accounts()
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status in (401, 403):
                raise IntegrationAccountListingError(
                    "Google rejected the credentials for this connection. Please reconnect the Google account "
                    "and grant access to AdMob."
                ) from e
            raise IntegrationAccountListingError(
                "Google is having trouble responding right now. Please try again in a few minutes."
            ) from e
        except (RetryableHTTPError, requests.RequestException) as e:
            raise IntegrationAccountListingError(
                "Google is having trouble responding right now. Please try again in a few minutes."
            ) from e

        return [
            IntegrationAccount(
                value=account["publisherId"],
                display_name=account["publisherId"],
                secondary_text=account.get("currencyCode"),
            )
            for account in accounts
            if account.get("publisherId")
        ]

    def get_schemas(
        self,
        config: GoogleAdMobSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=report.name,
                supports_incremental=True,
                supports_append=False,
                incremental_fields=DATE_INCREMENTAL_FIELDS,
                default_incremental_lookback_seconds=REVISION_LOOKBACK_SECONDS,
                detected_primary_keys=report.primary_keys,
            )
            for report in ADMOB_REPORTS.values()
        ] + [
            SourceSchema(
                name=list_config.name,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                detected_primary_keys=[list_config.primary_key],
            )
            for list_config in ADMOB_LISTS.values()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [schema for schema in schemas if schema.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: GoogleAdMobSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not config.google_admob_integration_id:
            return False, "Connect a Google account to sync AdMob."
        if not config.publisher_id:
            return False, "Pick the AdMob account to sync."

        try:
            access_token = self.access_token(config.google_admob_integration_id, team_id)
        except (ValueError, AdMobAuthError, AdMobTokenRefreshError) as e:
            return False, str(e)
        except requests.RequestException as e:
            return False, f"Could not reach Google to refresh this connection ({e}). Please retry."

        return validate_admob_credentials(
            access_token=access_token,
            publisher_id=config.publisher_id,
            start_date=config.start_date,
            api_version=self.resolve_api_version(api_version),
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AdMobResumeConfig]:
        return ResumableSourceManager[AdMobResumeConfig](inputs, AdMobResumeConfig)

    def source_for_pipeline(
        self,
        config: GoogleAdMobSourceConfig,
        resumable_source_manager: ResumableSourceManager[AdMobResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        integration_id = config.google_admob_integration_id
        team_id = inputs.team_id

        return google_admob_source(
            access_token=self.access_token(integration_id, team_id),
            refresh_access_token=lambda: self.access_token(integration_id, team_id, force_refresh=True),
            publisher_id=config.publisher_id,
            start_date=config.start_date,
            endpoint=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOOGLEADMOB,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Google AdMob",
            caption=(
                "Import daily AdMob earnings, impressions and clicks from the network and mediation reports, "
                "plus your apps and ad units.\n\n"
                "Connect the Google account that has access to your AdMob account, then pick the account to "
                "sync. PostHog asks for read-only access to your AdMob data."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/google-admob",
            iconPath="/static/services/google_admob.png",
            featureFlag="dwh-google-admob",
            releaseStatus=ReleaseStatus.BETA,
            keywords=["admob", "ads", "ad revenue"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="google_admob_integration_id",
                        label="Google account",
                        required=True,
                        kind=INTEGRATION_KIND,
                        requiredScopes=REQUIRED_SCOPES,
                    ),
                    SourceFieldOauthAccountSelectConfig(
                        name="publisher_id",
                        label="AdMob account",
                        integrationField="google_admob_integration_id",
                        integrationKind=INTEGRATION_KIND,
                        required=True,
                        placeholder="Pick an AdMob account the connected Google account can access",
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        sync_setting=True,
                        label="Start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="YYYY-MM-DD (defaults to the last 365 days)",
                        secret=False,
                    ),
                ],
            ),
        )
