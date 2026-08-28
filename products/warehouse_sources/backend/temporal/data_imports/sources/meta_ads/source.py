from datetime import date
from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthAccountSelectConfig,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
    SuggestedTable,
)

from posthog.models.integration import Integration

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP,
    FieldType,
    ResumableSource,
    VersionDeprecation,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.metaads import (
    MetaAdsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads import (
    META_ADS_API_VERSION_V25,
    META_ADS_API_VERSION_V26,
    META_AUTH_ERROR_MESSAGE,
    META_RATE_LIMIT_ERROR_MESSAGE,
    SHRINK_EXHAUSTED_ERROR_MESSAGE,
    MetaAdsAuthError,
    MetaAdsRateLimitError,
    MetaAdsResumeConfig,
    MetaAdsTokenRefreshError,
    get_integration_by_id,
    list_ad_accounts,
    meta_ads_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.schemas import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SHOULD_SYNC_DEFAULT,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Meta's numeric `account_status`, as the Ads Manager labels it. 201/202 (ANY_ACTIVE, ANY_CLOSED)
# are query filters rather than states an account is ever returned in, so they're absent here.
ACCOUNT_STATUS_LABELS = {
    1: "Active",
    2: "Disabled",
    3: "Unsettled",
    7: "Pending risk review",
    8: "Pending settlement",
    9: "In grace period",
    100: "Pending closure",
    101: "Closed",
}


def _status_badges(account: dict) -> tuple[str, ...]:
    status = account.get("account_status")
    label = ACCOUNT_STATUS_LABELS.get(status) if status is not None else None
    return (label,) if label else ()


@SourceRegistry.register
class MetaAdsSource(ResumableSource[MetaAdsSourceConfig, MetaAdsResumeConfig], OAuthMixin):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = (META_ADS_API_VERSION_V25, META_ADS_API_VERSION_V26)
    default_version = META_ADS_API_VERSION_V26
    api_docs_url = "https://developers.facebook.com/docs/graph-api/changelog"
    deprecated_versions = (VersionDeprecation(version=META_ADS_API_VERSION_V25, sunset_at=date(2028, 7, 29)),)

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
            # Graph API code 200: "Requires business_management permission to manage the object."
            # Distinct from the generic re-authorize message above — re-authorizing can never grant
            # this scope, since the Meta OAuth consent only requests `ads_read` (see
            # `AD_ACCOUNT_FIELDS` in meta_ads.py). Only the account owner granting
            # `business_management`, or PostHog dropping the field that needs it, fixes this.
            "Requires business_management permission": (
                "Meta rejected part of this request because it needs the business_management "
                "permission, which this integration does not request and cannot request without "
                "widening OAuth consent for every customer. Re-authorizing will not fix this — "
                "contact PostHog support if this table keeps failing."
            ),
            # Graph API code 100: the source's "Attribution windows for insights" setting (a
            # free-text field, see `SourceFieldInputConfig` above) contains a value Meta's
            # Insights API doesn't recognise. Retrying resends the same invalid parameter, so
            # only editing the source config fixes it. Matches the message regardless of which
            # array index Meta reports as invalid.
            "action_attribution_windows[": (
                'Meta rejected the "Attribution windows for insights" setting on this source — one '
                "of the configured values isn't a window Meta supports (e.g. 1d_click, 7d_click, "
                "28d_click, 1d_view, 7d_view, 28d_view). Fix it in your Meta Ads source settings, "
                "then run the sync again."
            ),
            # Meta returns this 500 when the requested query is too large for their backend to
            # service. Both pagination paths adapt to it (stats chunks shrink 30 → 7 → 1 day, and
            # both paths shrink the per-page limit 500 → 100 → 50); if it still escapes after those
            # fallbacks are exhausted, retrying the whole job won't help.
            "Please reduce the amount of data you're asking for": None,
            # Raised by `meta_ads._raise_shrink_exhausted_error` once both ladders
            # have bottomed out. The next attempt would re-issue the identical
            # single-day, smallest-page request that just failed, so the only thing
            # left is for the user to narrow the sync window.
            SHRINK_EXHAUSTED_ERROR_MESSAGE: (
                "Meta couldn't return this data even at the smallest request size. Lower the sync "
                "history for insights in your Meta Ads source settings, then run the sync again."
            ),
        }

    def get_retryable_errors(self) -> set[str]:
        return {
            # Meta error codes 1 ("API Unknown") and 2 ("API Service") are momentary backend blips
            # Meta's own docs recommend simply retrying. `meta_ads._raise_meta_api_error` tags them
            # with this marker once `_get_with_transient_retry`'s in-process retries are exhausted, so
            # the eventual Temporal-level retry doesn't page us as a bug.
            "Meta API request failed (retryable)",
            # Meta throttling (rate limiting) — the request itself is fine, Meta just rejected it
            # for volume. Only waiting helps, and the sync already retries via Temporal, so this
            # shouldn't page us as a bug either.
            META_RATE_LIMIT_ERROR_MESSAGE,
        }

    def get_schemas(
        self,
        config: MetaAdsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, should_sync_default=SHOULD_SYNC_DEFAULT)

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
            api_version=self.resolve_api_version(inputs.api_version),
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
            keywords=[
                "facebook ads",
                "instagram ads",
                "facebook",
                "instagram",
                "fb",
                "meta business",
                "meta business suite",
                "business manager",
                "facebook business",
            ],
            label="Meta Ads",
            caption="Ensure you have granted PostHog access to your Meta Ads account, learn how to do this in the [documentation](https://posthog.com/docs/cdp/sources/meta-ads).",
            iconPath="/static/services/meta-ads.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="meta_ads_integration_id",
                        label="Meta Ads account",
                        required=True,
                        kind="meta-ads",
                    ),
                    SourceFieldOauthAccountSelectConfig(
                        name="account_id",
                        label="Account ID",
                        integrationField="meta_ads_integration_id",
                        integrationKind="meta-ads",
                        required=True,
                    ),
                    SourceFieldInputConfig(
                        name="sync_lookback_days",
                        label="Sync history for insights (days) - applies to every stats table",
                        type=SourceFieldInputConfigType.NUMBER,
                        required=False,
                        placeholder="90",
                        secret=False,
                        caption=(
                            "A stats table that already imported keeps its current start date. A higher "
                            "value pulls in older data only after you resync that table."
                        ),
                    ),
                    # Attribution settings for insights (spend/conversion) tables. Left unset, Meta
                    # applies its own default, so existing connections are unaffected. Set them to
                    # reconcile PostHog's numbers with Ads Manager, which reports on a specific window.
                    SourceFieldInputConfig(
                        name="action_attribution_windows",
                        label="Attribution windows for insights (comma-separated, e.g. 7d_click,1d_view)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="7d_click,1d_view",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="use_unified_attribution_setting",
                        label="Use Meta's unified attribution setting",
                        required=False,
                        defaultValue="",
                        options=[
                            SourceFieldSelectConfigOption(label="Use Meta's default", value=""),
                            SourceFieldSelectConfigOption(label="Yes", value="true"),
                            SourceFieldSelectConfigOption(label="No", value="false"),
                        ],
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

    def get_oauth_accounts(
        self, integration_id: int, team_id: int, search: str | None = None
    ) -> list[IntegrationAccount]:
        # A Meta user's ad accounts are few, so `search` is ignored here and the endpoint filters the list.
        try:
            integration = get_integration_by_id(integration_id, team_id)
        except Integration.DoesNotExist as e:
            raise IntegrationAccountListingError(
                "The linked Meta Ads integration could not be found. Please reconnect your Meta Ads integration."
            ) from e
        except MetaAdsTokenRefreshError as e:
            raise IntegrationAccountListingError(str(e)) from e

        try:
            accounts = list_ad_accounts(integration)
        except MetaAdsAuthError as e:
            raise IntegrationAccountListingError(
                f"{META_AUTH_ERROR_MESSAGE} Make sure the connected account can access your ad accounts."
            ) from e
        except MetaAdsRateLimitError as e:
            # Throttling is not a bug: surface it as an actionable 400 the user can retry, rather
            # than a 500 that pages us.
            raise IntegrationAccountListingError(str(e)) from e

        return [
            IntegrationAccount(
                # Bare id, as the Ads Manager shows it; the pipeline's `_clean_account_id` adds the
                # `act_` prefix the Graph API wants.
                value=account["account_id"],
                display_name=account.get("name") or "Unnamed account",
                badges=_status_badges(account),
            )
            for account in accounts
        ]
