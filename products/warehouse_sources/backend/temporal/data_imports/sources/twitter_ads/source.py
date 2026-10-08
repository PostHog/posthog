from typing import cast
from urllib.parse import quote

import requests

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldOauthAccountSelectConfig,
    SourceFieldOauthConfig,
    SuggestedTable,
)
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    incremental_field,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.twitterads import (
    TwitterAdsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.twitter_ads.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.twitter_ads.settings import (
    ACCOUNT_ACCESS_DENIED,
    API_VERSION,
    ENTITY_TABLES,
    LOOKBACK_SECONDS,
    MISSING_APP,
    MISSING_INTEGRATION,
    PRIMARY_KEYS,
    REVOKED_GRANT,
    STATS_TABLES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.twitter_ads.twitter_ads import (
    TwitterAdsClient,
    TwitterAdsResumeConfig,
    twitter_ads_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TwitterAdsSource(ResumableSource[TwitterAdsSourceConfig, TwitterAdsResumeConfig], OAuthMixin):
    lists_tables_without_credentials = True
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = "https://docs.x.com/x-ads-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TWITTERADS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TWITTERADS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            keywords=["x ads", "twitter ads"],
            label="X Ads",
            iconPath="/static/services/twitter_ads.png",
            docsUrl="https://posthog.com/docs/cdp/sources/twitter-ads",
            releaseStatus=ReleaseStatus.ALPHA,
            # Hidden until PostHog's X app is approved for Ads API access and its keys are deployed.
            featureFlag="dwh-twitter-ads",
            suggestedTables=[
                SuggestedTable(table="campaigns", tooltip="Required for campaign names in Marketing analytics."),
                SuggestedTable(
                    table="campaign_stats",
                    tooltip="Required for daily spend, clicks, and impressions in Marketing analytics.",
                ),
                SuggestedTable(table="line_items", tooltip="Required for ad group names in Marketing analytics."),
                SuggestedTable(
                    table="line_item_stats", tooltip="Required for daily ad group metrics in Marketing analytics."
                ),
            ],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="twitter_ads_integration_id", label="X Ads account", required=True, kind="twitter-ads"
                    ),
                    SourceFieldOauthAccountSelectConfig(
                        name="account_id",
                        label="Ad account",
                        integrationField="twitter_ads_integration_id",
                        integrationKind="twitter-ads",
                        required=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": REVOKED_GRANT,
            "403 Client Error": ACCOUNT_ACCESS_DENIED,
            "Integration not found": MISSING_INTEGRATION,
            "Missing integration ID": MISSING_INTEGRATION,
            MISSING_INTEGRATION: MISSING_INTEGRATION,
            MISSING_APP: MISSING_APP,
        }

    def get_oauth_accounts(
        self, integration_id: int, team_id: int, search: str | None = None
    ) -> list[IntegrationAccount]:
        try:
            client = TwitterAdsClient(self.get_oauth_integration(integration_id, team_id))
            return [
                IntegrationAccount(value=row["id"], display_name=row.get("name") or row["id"], secondary_text=row["id"])
                for page in client.pages("accounts")
                for row in page["data"]
                if not row.get("deleted")
            ]
        except ValueError as error:
            raise IntegrationAccountListingError(
                MISSING_APP if str(error) == MISSING_APP else MISSING_INTEGRATION
            ) from None
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status in (401, 403):
                raise IntegrationAccountListingError(
                    REVOKED_GRANT if status == 401 else ACCOUNT_ACCESS_DENIED
                ) from None
            raise
        except requests.RequestException:
            raise IntegrationAccountListingError("Could not reach X Ads. Please try again.") from None

    def validate_credentials(
        self,
        config: TwitterAdsSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            client = TwitterAdsClient(
                self.get_oauth_integration(config.twitter_ads_integration_id, team_id), api_version or API_VERSION
            )
            client.get(f"accounts/{quote(config.account_id, safe='')}", {"with_deleted": "true"})
            return True, None
        except ValueError as error:
            return False, MISSING_APP if str(error) == MISSING_APP else MISSING_INTEGRATION
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            return (
                False,
                REVOKED_GRANT
                if status == 401
                else ACCOUNT_ACCESS_DENIED
                if status == 403
                else "X Ads could not validate this ad account. Please try again.",
            )
        except requests.RequestException:
            return False, "Could not reach X Ads. Please try again."

    def get_schemas(
        self,
        config: TwitterAdsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=name,
                supports_incremental=name in STATS_TABLES,
                supports_append=False,
                incremental_fields=[incremental_field("date")] if name in STATS_TABLES else [],
                default_incremental_lookback_seconds=LOOKBACK_SECONDS if name in STATS_TABLES else None,
                detected_primary_keys=PRIMARY_KEYS[name],
            )
            for name in (*ENTITY_TABLES, *STATS_TABLES)
            if names is None or name in names
        ]

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TwitterAdsResumeConfig]:
        return ResumableSourceManager(inputs, TwitterAdsResumeConfig)

    def source_for_pipeline(
        self,
        config: TwitterAdsSourceConfig,
        resumable_source_manager: ResumableSourceManager[TwitterAdsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        client = TwitterAdsClient(
            self.get_oauth_integration(config.twitter_ads_integration_id, inputs.team_id),
            inputs.api_version or API_VERSION,
        )
        return twitter_ads_source(
            client,
            config.account_id,
            inputs.schema_name,
            resumable_source_manager,
            inputs.db_incremental_field_last_value if inputs.should_use_incremental_field else None,
        )
