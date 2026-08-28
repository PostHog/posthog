from typing import Optional, cast

import requests

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthAccountSelectConfig,
    SourceFieldOauthConfig,
)

from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, OauthIntegration

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.youtubeanalytics import (
    YouTubeAnalyticsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.youtube_analytics.settings import (
    DAY_INCREMENTAL_FIELDS,
    REQUIRED_SCOPES,
    REVISION_LOOKBACK_SECONDS,
    YOUTUBE_ANALYTICS_REPORTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.youtube_analytics.youtube_analytics import (
    YouTubeAnalyticsAuthError,
    YouTubeAnalyticsResumeConfig,
    list_channels,
    validate_credentials as validate_youtube_analytics_credentials,
    youtube_analytics_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

RECONNECT_MESSAGE = (
    "Could not use the credentials for this YouTube Analytics connection. Please reconnect the Google account."
)


@SourceRegistry.register
class YouTubeAnalyticsSource(ResumableSource[YouTubeAnalyticsSourceConfig, YouTubeAnalyticsResumeConfig], OAuthMixin):
    api_docs_url = "https://developers.google.com/youtube/analytics/reference/reports/query"
    supported_versions = ("v2",)
    default_version = "v2"

    lists_tables_without_credentials = True  # static report catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.YOUTUBEANALYTICS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": (
                "Google rejected the credentials for this connection. Please reconnect the Google account."
            ),
            "403 Client Error: Forbidden for url: https://youtubeanalytics.googleapis.com": (
                "The connected Google account cannot read this channel's analytics. Reconnect using an "
                "account that manages the channel, and grant the YouTube Analytics permission."
            ),
            "Integration not found": (
                "The Google account for this source is no longer connected. Please reconnect it."
            ),
            # Already the actionable message, so keep it rather than substituting another.
            RECONNECT_MESSAGE: None,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.youtube_analytics.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def access_token(self, integration_id: int, team_id: int, force_refresh: bool = False) -> str:
        """A currently valid Google access token for the linked account.

        `force_refresh` re-mints unconditionally, for the mid-sync case where a token that looked
        fresh has already been rejected.
        """
        integration = self.get_oauth_integration(integration_id, team_id)

        oauth = OauthIntegration(integration)
        if force_refresh or oauth.access_token_expired():
            oauth.refresh_access_token()
            if integration.errors == ERROR_TOKEN_REFRESH_FAILED:
                raise YouTubeAnalyticsAuthError(RECONNECT_MESSAGE)

        if not integration.access_token:
            raise YouTubeAnalyticsAuthError(RECONNECT_MESSAGE)

        return integration.access_token

    def get_oauth_accounts(
        self, integration_id: int, team_id: int, search: str | None = None
    ) -> list[IntegrationAccount]:
        # A Google account owns a handful of channels at most, so `search` is ignored here and the
        # endpoint filters the returned list.
        try:
            access_token = self.access_token(integration_id, team_id)
        except ValueError as e:
            raise IntegrationAccountListingError(
                "The Google account for this source is no longer connected. Please reconnect it."
            ) from e
        except YouTubeAnalyticsAuthError as e:
            raise IntegrationAccountListingError(str(e)) from e
        except requests.RequestException as e:
            # `refresh_access_token` only records the failure on the integration when Google answers
            # with a parseable body; a network error or an HTML error page escapes instead.
            raise IntegrationAccountListingError(
                "Could not reach Google to refresh this connection. Please try again in a few minutes."
            ) from e

        try:
            channels = list_channels(access_token)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status in (401, 403):
                raise IntegrationAccountListingError(
                    "Google rejected the credentials for this connection. Please reconnect the Google account "
                    "and grant access to your YouTube channel."
                ) from e
            if status == 429 or (status is not None and status >= 500):
                raise IntegrationAccountListingError(
                    "Google is having trouble responding right now. Please try again in a few minutes."
                ) from e
            # Any other status means we built a bad request, which the user cannot fix.
            raise
        except requests.RequestException as e:
            raise IntegrationAccountListingError(
                "Google is having trouble responding right now. Please try again in a few minutes."
            ) from e

        return [
            IntegrationAccount(
                value=channel["id"],
                display_name=(channel.get("snippet") or {}).get("title") or channel["id"],
                secondary_text=(channel.get("snippet") or {}).get("customUrl"),
            )
            for channel in channels
            if channel.get("id")
        ]

    def get_schemas(
        self,
        config: YouTubeAnalyticsSourceConfig,
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
                incremental_fields=DAY_INCREMENTAL_FIELDS,
                # YouTube keeps restating the most recent days, so re-read a trailing window
                # every incremental run instead of freezing a day at its first-imported value.
                default_incremental_lookback_seconds=REVISION_LOOKBACK_SECONDS,
                detected_primary_keys=report.primary_keys,
            )
            for report in YOUTUBE_ANALYTICS_REPORTS.values()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [schema for schema in schemas if schema.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: YouTubeAnalyticsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not config.youtube_analytics_integration_id:
            return False, "Connect a Google account to sync YouTube Analytics."

        try:
            access_token = self.access_token(config.youtube_analytics_integration_id, team_id)
        except (ValueError, YouTubeAnalyticsAuthError) as e:
            return False, str(e)
        except requests.RequestException as e:
            return False, f"Could not reach Google to refresh this connection ({e}). Please retry."

        return validate_youtube_analytics_credentials(
            access_token=access_token,
            channel_id=config.channel_id,
            start_date=config.start_date,
            api_version=self.resolve_api_version(api_version),
        )

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[YouTubeAnalyticsResumeConfig]:
        return ResumableSourceManager[YouTubeAnalyticsResumeConfig](inputs, YouTubeAnalyticsResumeConfig)

    def source_for_pipeline(
        self,
        config: YouTubeAnalyticsSourceConfig,
        resumable_source_manager: ResumableSourceManager[YouTubeAnalyticsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        integration_id = config.youtube_analytics_integration_id
        team_id = inputs.team_id

        return youtube_analytics_source(
            access_token=self.access_token(integration_id, team_id),
            refresh_access_token=lambda: self.access_token(integration_id, team_id, force_refresh=True),
            channel_id=config.channel_id,
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
            name=SchemaExternalDataSourceType.YOU_TUBE_ANALYTICS,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="YouTube Analytics",
            caption=(
                "Pull daily channel metrics from the YouTube Analytics API: views, watch time, subscribers, "
                "traffic sources, geography and demographics.\n\n"
                "Connect the Google account that manages your channel, then pick the channel to sync. PostHog "
                "asks for read-only access to your YouTube Analytics reports and your list of channels."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/youtube-analytics",
            iconPath="/static/services/youtube_analytics.png",
            featureFlag="dwh_youtube_analytics",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["youtube", "yt"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="youtube_analytics_integration_id",
                        label="Google account",
                        required=True,
                        kind="youtube-analytics",
                        requiredScopes=REQUIRED_SCOPES,
                    ),
                    SourceFieldOauthAccountSelectConfig(
                        name="channel_id",
                        label="Channel",
                        integrationField="youtube_analytics_integration_id",
                        integrationKind="youtube-analytics",
                        required=True,
                        placeholder="Pick a channel the connected account owns",
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="YYYY-MM-DD (defaults to the last 365 days)",
                        secret=False,
                    ),
                ],
            ),
        )
