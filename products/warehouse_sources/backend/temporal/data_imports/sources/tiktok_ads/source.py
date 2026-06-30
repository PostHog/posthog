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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TikTokAdsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tiktok_ads.settings import TIKTOK_ADS_CONFIG
from products.warehouse_sources.backend.temporal.data_imports.sources.tiktok_ads.tiktok_ads import (
    TikTokAdsResumeConfig,
    tiktok_ads_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tiktok_ads.utils import (
    TIKTOK_NON_RETRYABLE_ERROR_PREFIX,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TikTokAdsSource(ResumableSource[TikTokAdsSourceConfig, TikTokAdsResumeConfig], OAuthMixin):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TIKTOKADS

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.tiktok_ads.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # TikTok client errors not in the retryable code set (e.g. 40001 — the advertiser
            # doesn't exist or has been deleted). The paginator raises these with this exact
            # prefix; retrying cannot recover, so fail the job fast. The raw message is kept as
            # the user-facing error since it names the specific advertiser and TikTok error code.
            TIKTOK_NON_RETRYABLE_ERROR_PREFIX: None,
            # Integration row was deleted/disconnected while a scheduled job still references it.
            # Raised by OAuthMixin.get_oauth_integration as `ValueError("Integration not found: <id>")`;
            # the id is volatile, so match only the stable prefix. Retrying can't recreate the row —
            # the customer has to reconnect.
            "Integration not found": "The linked TikTok Ads integration no longer exists. Please reconnect your TikTok Ads integration.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TIK_TOK_ADS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="TikTok Ads",
            caption="Collect campaign data, ad performance, and advertising metrics from TikTok Ads. Ensure you have granted PostHog access to your TikTok Ads account, learn how to do this in [the documentation](https://posthog.com/docs/cdp/sources/tiktok-ads).",
            releaseStatus=ReleaseStatus.GA,
            iconPath="/static/services/tiktok.png",
            docsUrl="https://posthog.com/docs/cdp/sources/tiktok-ads",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="advertiser_id",
                        label="TikTok Ads Advertiser ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="Your TikTok Ads advertiser ID",
                        secret=False,
                    ),
                    SourceFieldOauthConfig(
                        name="tiktok_integration_id",
                        label="TikTok Ads account",
                        required=True,
                        kind="tiktok-ads",
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
        self, config: TikTokAdsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if not config.advertiser_id or not config.tiktok_integration_id:
            return False, "Advertiser ID and TikTok Ads integration are required"

        try:
            self.get_oauth_integration(config.tiktok_integration_id, team_id)
            return True, None
        except Exception as e:
            capture_exception(e)
            return False, f"Failed to validate TikTok Ads credentials: {str(e)}"

    def get_schemas(
        self,
        config: TikTokAdsSourceConfig,
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
            for endpoint_config in TIKTOK_ADS_CONFIG.values()
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TikTokAdsResumeConfig]:
        return ResumableSourceManager[TikTokAdsResumeConfig](inputs, TikTokAdsResumeConfig)

    def source_for_pipeline(
        self,
        config: TikTokAdsSourceConfig,
        resumable_source_manager: ResumableSourceManager[TikTokAdsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        integration = self.get_oauth_integration(config.tiktok_integration_id, inputs.team_id)

        if not integration.access_token:
            raise ValueError(f"TikTok Ads access token not found for job {inputs.job_id}")

        return tiktok_ads_source(
            advertiser_id=config.advertiser_id,
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
