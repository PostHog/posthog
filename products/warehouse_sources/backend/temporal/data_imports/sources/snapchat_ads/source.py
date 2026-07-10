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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SnapchatAdsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.snapchat_ads.settings import SNAPCHAT_ADS_CONFIG
from products.warehouse_sources.backend.temporal.data_imports.sources.snapchat_ads.snapchat_ads import (
    SnapchatResumeConfig,
    snapchat_ads_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SnapchatAdsSource(ResumableSource[SnapchatAdsSourceConfig, SnapchatResumeConfig], OAuthMixin):
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://developers.snap.com/api/marketing-api"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SNAPCHATADS

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.snapchat_ads.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Snapchat's Marketing API surfaces these as requests HTTPError "<code> Client Error".
        # They're all permanent for a given config — a deleted/inaccessible ad account (404),
        # revoked auth (401), or insufficient permissions (403) — so retrying cannot recover.
        return {
            "401 Client Error": "Snapchat Ads authentication failed. Please reconnect your Snapchat account.",
            "403 Client Error": "Snapchat Ads access forbidden. Please check your account permissions.",
            "404 Client Error": "Snapchat Ads resource not found. Please check that the ad account still exists and is accessible.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SNAPCHAT_ADS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Snapchat Ads",
            caption="Collect campaign data, ad performance, and advertising metrics from Snapchat Ads. Ensure you have granted PostHog access to your Snapchat Ads account, learn how to do this in [the documentation](https://posthog.com/docs/cdp/sources/snapchat-ads).",
            releaseStatus=ReleaseStatus.GA,
            iconPath="/static/services/snapchat.png",
            docsUrl="https://posthog.com/docs/cdp/sources/snapchat-ads",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="ad_account_id",
                        label="Snapchat Ads Ad Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="Your Snapchat Ads ad account ID",
                        secret=False,
                    ),
                    SourceFieldOauthConfig(
                        name="snapchat_integration_id",
                        label="Snapchat Ads account",
                        required=True,
                        kind="snapchat",
                    ),
                ],
            ),
            suggestedTables=[
                SuggestedTable(
                    table="campaigns",
                    tooltip=MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP,
                ),
                SuggestedTable(
                    table="campaign_stats_daily",
                    tooltip=MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP,
                ),
            ],
        )

    def validate_credentials(
        self, config: SnapchatAdsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if not config.ad_account_id or not config.snapchat_integration_id:
            return False, "Ad Account ID and Snapchat Ads integration are required"

        try:
            self.get_oauth_integration(config.snapchat_integration_id, team_id)
            return True, None
        except Exception as e:
            capture_exception(e)
            return False, f"Failed to validate Snapchat Ads credentials: {str(e)}"

    def get_schemas(
        self,
        config: SnapchatAdsSourceConfig,
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
            for endpoint_config in SNAPCHAT_ADS_CONFIG.values()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SnapchatResumeConfig]:
        return ResumableSourceManager[SnapchatResumeConfig](inputs, SnapchatResumeConfig)

    def source_for_pipeline(
        self,
        config: SnapchatAdsSourceConfig,
        resumable_source_manager: ResumableSourceManager[SnapchatResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        integration = self.get_oauth_integration(config.snapchat_integration_id, inputs.team_id)

        if not integration.access_token:
            raise ValueError(f"Snapchat Ads access token not found for job {inputs.job_id}")

        return snapchat_ads_source(
            ad_account_id=config.ad_account_id,
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
