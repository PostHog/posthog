from typing import cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MetaAdsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads import (
    META_AUTH_ERROR_MESSAGE,
    MetaAdsResumeConfig,
    meta_ads_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.schemas import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MetaAdsSource(ResumableSource[MetaAdsSourceConfig, MetaAdsResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.METAADS

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "Failed to refresh token for Meta Ads integration. Please re-authorize the integration.": None,
            # The data warehouse source still references a `meta_ads_integration_id` whose
            # Integration row no longer exists for the team (the integration was deleted or
            # de-authorized). `get_integration` then raises Django's `Integration.DoesNotExist`
            # ("Integration matching query does not exist."); retrying can never make the row
            # reappear — the only fix is the user reconnecting the integration.
            "Integration matching query does not exist.": (
                "The Meta Ads integration for this source no longer exists. Please reconnect the Meta Ads integration."
            ),
            # Permanent auth/permission failures from the Graph API (e.g. revoked or expired
            # access tokens, checkpoint-required, invalidated sessions, permission denials).
            # `meta_ads._raise_meta_api_error` prefixes these with this exact message.
            META_AUTH_ERROR_MESSAGE: META_AUTH_ERROR_MESSAGE,
            # Graph API code 200: "Ad account owner has NOT granted ads_management or ads_read
            # permission." The connected Meta user can't read this ad account's data. Retrying
            # can't grant the permission — the account owner has to. Without a message here the
            # raw Graph API JSON blob surfaces to the user, so give actionable guidance instead.
            "Ad account owner has NOT": (
                "Meta denied access to this ad account — the connected Meta account is missing the "
                "ads_read permission needed to sync its data. Ask the ad account owner to grant that "
                "access, then reconnect the Meta Ads integration."
            ),
            # Graph API code 100: "This endpoint cannot be loaded due to missing permissions." A
            # specific endpoint can't be read with the permissions the user granted. Same as above:
            # not fixable by retrying, and the raw JSON would otherwise reach the user.
            "cannot be loaded due to missing permissions": (
                "Meta blocked this request because the connected account is missing a permission "
                "required to read your ads data. Please reconnect the Meta Ads integration and grant "
                "all requested permissions."
            ),
            # Meta returns this 500 when the requested query is too large for their backend to
            # service. Both pagination paths adapt to it (stats chunks shrink 30 → 7 → 1 day, and
            # both paths shrink the per-page limit 500 → 100 → 50); if it still escapes after those
            # fallbacks are exhausted, retrying the whole job won't help.
            "Please reduce the amount of data you're asking for": None,
        }

    def get_schemas(
        self,
        config: MetaAdsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MetaAdsResumeConfig]:
        return ResumableSourceManager[MetaAdsResumeConfig](inputs, MetaAdsResumeConfig)

    def source_for_pipeline(
        self,
        config: MetaAdsSourceConfig,
        resumable_source_manager: ResumableSourceManager[MetaAdsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return meta_ads_source(
            resource_name=inputs.schema_name,
            config=config,
            team_id=inputs.team_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field if inputs.should_use_incremental_field else None,
            incremental_field_type=inputs.incremental_field_type if inputs.should_use_incremental_field else None,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.META_ADS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            featured=True,
            keywords=["facebook ads", "instagram ads", "facebook", "instagram", "fb"],
            label="Meta Ads",
            caption="Ensure you have granted PostHog access to your Meta Ads account, learn how to do this in the [documentation](https://posthog.com/docs/cdp/sources/meta-ads).",
            iconPath="/static/services/meta-ads.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldOauthConfig(
                        name="meta_ads_integration_id",
                        label="Meta Ads account",
                        required=True,
                        kind="meta-ads",
                    ),
                    SourceFieldInputConfig(
                        name="sync_lookback_days",
                        label="Sync history for insights (days) - applies to AdStats, AdsetStats, CampaignStats",
                        type=SourceFieldInputConfigType.NUMBER,
                        required=False,
                        placeholder="90",
                        secret=False,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.GA,
            suggestedTables=[
                SuggestedTable(
                    table="campaigns",
                    tooltip=MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP,
                ),
                SuggestedTable(
                    table="campaign_stats",
                    tooltip=MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP,
                ),
            ],
        )
