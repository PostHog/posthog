from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RedditAdsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.reddit_ads.reddit_ads import (
    RedditAdsResumeConfig,
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
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Reddit Ads Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="Your Reddit Ads account ID",
                        secret=False,
                    ),
                    SourceFieldOauthConfig(
                        name="reddit_integration_id",
                        label="Reddit Ads account",
                        required=True,
                        kind="reddit-ads",
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
