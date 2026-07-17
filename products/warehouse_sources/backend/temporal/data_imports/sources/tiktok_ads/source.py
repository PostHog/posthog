from typing import Optional, cast

from requests.exceptions import HTTPError, RequestException

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TikTokAdsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tiktok_ads.settings import TIKTOK_ADS_CONFIG
from products.warehouse_sources.backend.temporal.data_imports.sources.tiktok_ads.tiktok_ads import (
    TikTokAdsResumeConfig,
    tiktok_ads_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tiktok_ads.utils import (
    TIKTOK_AUTH_ERROR_CODES,
    TIKTOK_NON_RETRYABLE_ERROR_PREFIX,
    TIKTOK_TRANSIENT_ERROR_CODES,
    TIKTOK_TRANSIENT_ERROR_MESSAGE,
    TikTokAdsAPIError,
    list_advertisers,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TikTokAdsSource(ResumableSource[TikTokAdsSourceConfig, TikTokAdsResumeConfig], OAuthMixin):
    supported_versions = ("v1.3",)
    default_version = "v1.3"
    api_docs_url = "https://business-api.tiktok.com/portal/docs"

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
                    SourceFieldOauthConfig(
                        name="tiktok_integration_id",
                        label="TikTok Ads account",
                        required=True,
                        kind="tiktok-ads",
                    ),
                    SourceFieldOauthAccountSelectConfig(
                        name="advertiser_id",
                        label="TikTok Ads Advertiser ID",
                        integrationField="tiktok_integration_id",
                        integrationKind="tiktok-ads",
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
        # A user authorizes few advertisers, so `search` is ignored here and the endpoint filters the list.
        try:
            integration = self.get_oauth_integration(integration_id, team_id)
        except ValueError as e:
            raise IntegrationAccountListingError(
                "The linked TikTok Ads integration could not be found. Please reconnect your TikTok Ads integration."
            ) from e

        # TikTok's token response carries no refresh_token and no expires_in, so the token never
        # expires from our side and there is nothing to refresh — an absent one means a broken row.
        if not integration.access_token:
            raise IntegrationAccountListingError("The TikTok Ads integration has no access token. Please reconnect it.")

        try:
            advertisers = list_advertisers(integration.access_token)
        except HTTPError as e:
            # TikTok's edge (not the API itself) returned a real 429/5xx — transient and TikTok-side.
            status_code = e.response.status_code if e.response is not None else None
            if status_code is None or (status_code < 500 and status_code != 429):
                raise
            raise IntegrationAccountListingError(TIKTOK_TRANSIENT_ERROR_MESSAGE) from e
        except RequestException as e:
            # DNS failure, connection reset, or timeout (no HTTP response at all). These raise a
            # bare RequestException — not HTTPError — so they'd otherwise escape as a generic 500.
            # Transient and TikTok/network-side: map to the same actionable "try again" message.
            raise IntegrationAccountListingError(TIKTOK_TRANSIENT_ERROR_MESSAGE) from e
        except TikTokAdsAPIError as e:
            if e.api_code in TIKTOK_AUTH_ERROR_CODES:
                raise IntegrationAccountListingError(
                    "TikTok rejected the credentials for this integration. Please reconnect your TikTok Ads "
                    "integration and make sure the connected account can access your advertiser accounts."
                ) from e
            if e.api_code in TIKTOK_TRANSIENT_ERROR_CODES:
                raise IntegrationAccountListingError(TIKTOK_TRANSIENT_ERROR_MESSAGE) from e
            # Not something the user can fix (e.g. app-config mismatch, malformed body) — surface it.
            raise

        return [
            IntegrationAccount(
                value=advertiser["advertiser_id"],
                display_name=advertiser.get("advertiser_name") or "Unnamed account",
            )
            for advertiser in advertisers
        ]

    def validate_credentials(
        self,
        config: TikTokAdsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
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
        api_version: str | None = None,
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
