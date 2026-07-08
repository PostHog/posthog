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
from posthog.models.integration import Integration

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LinkedinAdsSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

from .linkedin_ads import (
    LinkedInAdsResumeConfig,
    get_incremental_fields as get_linkedin_ads_incremental_fields,
    get_schemas as get_linkedin_ads_schemas,
    linkedin_ads_source,
)


@SourceRegistry.register
class LinkedInAdsSource(ResumableSource[LinkedinAdsSourceConfig, LinkedInAdsResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LINKEDINADS

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "REVOKED_ACCESS_TOKEN": None,
            "The token used in the request has expired": "Failed to refresh token for LinkedIn Ads integration. Please re-authorize the integration.",
            # Raised by `linkedin_ads_client` when an expired access token can't be refreshed (revoked
            # or expired refresh token). The only fix is the user re-authorizing, so stop retrying. The
            # message is already user-facing, so map it to itself (None).
            "Failed to refresh token for LinkedIn Ads integration. Please re-authorize the integration.": None,
            # LinkedIn rejects a non-numeric Account ID with a 400 whose message names the offending
            # key value (volatile) followed by this stable type-coercion phrase. The account id is a
            # fixed config value, so retrying can't help — fail fast and tell the user to fix it.
            "must be of type 'java.lang.Long'": "LinkedIn rejected the configured Account ID. It must be the numeric LinkedIn ad account ID (digits only). Please correct the Account ID in your source settings and re-sync.",
            # LinkedIn returns a 404 with this stable error code when the requested ad account /
            # resource can't be resolved — typically a deleted account, a wrong Account ID, or lost
            # access. Retrying can't recover it, so stop syncing instead of looping the 404.
            "RESOURCE_NOT_FOUND": "LinkedIn could not find the requested ad account. It may have been deleted, the configured Account ID may be wrong, or PostHog may have lost access. Check the Account ID and re-authorize the LinkedIn Ads integration.",
            # LinkedIn returns a 401 with this stable error code when the member who authorized the
            # integration has been restricted on LinkedIn's side (suspended / flagged account). The
            # token can't be used until LinkedIn lifts the restriction, so retrying never recovers —
            # stop syncing and tell the user to resolve it with LinkedIn and re-authorize.
            "RESTRICTED_MEMBER": "LinkedIn has restricted the account that authorized this integration, so PostHog can no longer access your ad data. Resolve the restriction with LinkedIn, then re-authorize the LinkedIn Ads integration.",
            # The Account ID is a free-text field. A malformed value (a profile URL, a name, stray
            # whitespace) makes LinkedIn reject the `urn:li:sponsoredAccount:<id>` accounts param with
            # a deterministic 400 ("...is invalid. Reason: Deserializing output ... failed"). Retrying
            # never succeeds, so fail fast and tell the user to fix the configured Account ID. Match on
            # the stable prefix only — the offending value that follows varies per source.
            "Array parameter 'accounts' value 'urn:li:sponsoredAccount:": "The LinkedIn Ads Account ID is invalid. Please check the Account ID in your source configuration — it should be the numeric account ID from your LinkedIn Campaign Manager.",
            # Integration.DoesNotExist raised by `_get_integration` when the stored OAuth integration
            # row has been deleted/disconnected before the sync runs. Retrying cannot recover — the
            # user must re-authorize. Model-specific so we don't swallow unrelated `DoesNotExist`
            # errors from other models, which may be real bugs.
            "Integration matching query does not exist": "Your LinkedIn Ads connection is no longer available — it may have been disconnected. Please re-authorize the LinkedIn Ads integration.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LINKEDIN_ADS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            featured=True,
            keywords=["linkedin advertising"],
            label="LinkedIn Ads",
            caption="Ensure you have granted PostHog access to your LinkedIn Ads account, learn how to do this in [the documentation](https://posthog.com/docs/cdp/sources/linkedin-ads).",
            releaseStatus=ReleaseStatus.GA,
            iconPath="/static/services/linkedin.png",
            docsUrl="https://posthog.com/docs/cdp/sources/linkedin-ads",
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
                        name="linkedin_ads_integration_id",
                        label="LinkedIn Ads account",
                        required=True,
                        kind="linkedin-ads",
                    ),
                ],
            ),
            suggestedTables=[
                SuggestedTable(
                    table="campaign_groups",
                    tooltip=MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP,
                ),
                SuggestedTable(
                    table="campaign_group_stats",
                    tooltip=MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP,
                ),
            ],
        )

    def validate_credentials(
        self, config: LinkedinAdsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if not config.account_id or not config.linkedin_ads_integration_id:
            return False, "Account ID and LinkedIn Ads integration are required"

        # LinkedIn only accepts the numeric ad account ID. A free-text value (a profile URL, a
        # name, stray whitespace) is otherwise accepted here and only fails on the first sync, so
        # reject it up front with the same guidance the sync-time error gives.
        if not config.account_id.isdigit():
            return (
                False,
                "The LinkedIn Ads Account ID must be the numeric account ID from your LinkedIn Campaign Manager (digits only).",
            )

        try:
            Integration.objects.get(id=config.linkedin_ads_integration_id, team_id=team_id)
            return True, None
        except Integration.DoesNotExist:
            return False, "LinkedIn Ads integration not found. Please re-authenticate."
        except Exception as e:
            capture_exception(e)
            return False, f"Failed to validate LinkedIn Ads credentials: {str(e)}"

    def get_schemas(
        self,
        config: LinkedinAdsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        linkedin_ads_schemas = get_linkedin_ads_schemas()
        ads_incremental_fields = get_linkedin_ads_incremental_fields()

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
            for endpoint in linkedin_ads_schemas.keys()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LinkedInAdsResumeConfig]:
        return ResumableSourceManager[LinkedInAdsResumeConfig](inputs, LinkedInAdsResumeConfig)

    def source_for_pipeline(
        self,
        config: LinkedinAdsSourceConfig,
        resumable_source_manager: ResumableSourceManager[LinkedInAdsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return linkedin_ads_source(
            config=config,
            resource_name=inputs.schema_name,
            team_id=inputs.team_id,
            resumable_source_manager=resumable_source_manager,
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field if inputs.should_use_incremental_field else None,
            incremental_field_type=inputs.incremental_field_type if inputs.should_use_incremental_field else None,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
