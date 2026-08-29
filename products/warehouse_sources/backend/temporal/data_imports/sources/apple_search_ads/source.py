from datetime import date
from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.apple_search_ads import (
    AppleSearchAdsCredentials,
    AppleSearchAdsResumeConfig,
    apple_search_ads_source,
    validate_credentials as validate_apple_search_ads_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.settings import (
    APPLE_ADS_API_VERSION_V1,
    APPLE_SEARCH_ADS_API_VERSION_V5,
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    REPORT_ENDPOINTS,
    REPORT_LOOKBACK_SECONDS,
    endpoints_for_version,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    FieldType,
    ResumableSource,
    VersionDeprecation,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.applesearchads import (
    AppleSearchAdsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AppleSearchAdsSource(ResumableSource[AppleSearchAdsSourceConfig, AppleSearchAdsResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = (APPLE_SEARCH_ADS_API_VERSION_V5, APPLE_ADS_API_VERSION_V1)
    default_version = APPLE_ADS_API_VERSION_V1
    # Apple sunsets the Campaign Management API 5 on 2027-01-26, after which its endpoints stop
    # serving. A pinned source cannot be repinned for it: the Platform API scopes requests to
    # an ad account id, which is not derivable from the stored organization id.
    deprecated_versions = (VersionDeprecation(version=APPLE_SEARCH_ADS_API_VERSION_V5, sunset_at=date(2027, 1, 26)),)
    api_docs_url = "https://developer.apple.com/documentation/apple-ads-platform-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.APPLESEARCHADS

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored private key is sent against whichever ad account (Platform API) or
        # organization (v5) is configured, so changing either retargets the saved credential at a
        # different Apple account — force secret re-entry on a change to either.
        return ["ad_account_id", "org_id"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "400 Client Error: Bad Request for url: https://appleid.apple.com/auth/oauth2/token": "Apple rejected the signed client secret. Check your client ID, team ID, key ID and private key.",
            "401 Client Error: Unauthorized for url: https://appleid.apple.com/auth/oauth2/token": "Apple rejected the signed client secret. Check your client ID, team ID, key ID and private key.",
            "401 Client Error: Unauthorized for url: https://api.ads.apple.com": "Apple rejected the access token. Your API client may have been removed. Create a new one in Apple Ads and reconnect this source.",
            "403 Client Error: Forbidden for url: https://api.ads.apple.com": "Apple denied access to this ad account. Check that the API client has the API Account Read Only role for the ad account ID you entered.",
            "404 Client Error: Not Found for url: https://api.ads.apple.com": "Apple could not find this ad account. Check the ad account ID, which you can read from `adAccount.id` in Apple's Get User ACL endpoint.",
            "401 Client Error: Unauthorized for url: https://api.searchads.apple.com": "Apple Search Ads rejected the access token. Your API key may have been revoked. Generate a new one and reconnect this source.",
            "403 Client Error: Forbidden for url: https://api.searchads.apple.com": "Apple Search Ads denied access to this organization. Check that the API user has at least read access to the organization ID you entered.",
            "Could not sign the Apple Ads client secret": "The private key isn't a valid unencrypted EC (P-256) PEM. Paste the key you generated for your Apple Ads API client and reconnect.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.APPLE_SEARCH_ADS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Apple Ads",
            caption="""Connect your Apple Ads account, formerly Apple Search Ads, to pull campaigns, ad groups, keywords and daily performance into the PostHog Data warehouse.

Apple does not generate an API key for you. An account admin creates an API client, and you supply your own key pair:

1. Generate an EC P-256 key pair. On macOS or Linux, run `openssl ecparam -genkey -name prime256v1 -noout -out private-key.pem` and then `openssl ec -in private-key.pem -pubout -out public-key.pem`.
2. In [Apple Ads](https://ads.apple.com), open **Account settings > API** and add an API client. Paste the contents of `public-key.pem` into the public key field and save it.
3. Apple then shows the client ID, team ID and key ID. Enter those below, along with the contents of `private-key.pem`.
4. Read your ad account ID from Apple's Get User ACL endpoint, `GET https://api.ads.apple.com/v1/acls`, under `adAccount.id`. This is not the same value as your organization ID.

PostHog stores the private key encrypted and uses it to sign a short-lived token on every sync. The token itself is never stored.

Reporting tables use daily granularity, which Apple serves for the last 90 days only.""",
            permissionsCaption="""Give the API client the **API Account Read Only** role, which grants read access to the campaign data these tables are built from. The **API Account Manager** role also works if you already use it.""",
            iconPath="/static/services/apple_search_ads.png",
            docsUrl="https://posthog.com/docs/cdp/sources/apple-search-ads",
            releaseStatus=ReleaseStatus.ALPHA,
            # "Apple Search Ads" is the former product name, kept so the catalog still finds
            # this source under what Apple used to call it.
            keywords=["apple search ads", "asa", "app store ads", "search ads", "apple maps ads"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="ad_account_id",
                        label="Ad account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        # Optional at the form level because a source pinned to Apple's older
                        # API needs the organization ID below instead. `validate_credentials`
                        # requires whichever one the source's API version uses.
                        required=False,
                        placeholder="123456789",
                        caption="Read this from `adAccount.id` in the response from Apple's Get User ACL endpoint, `GET https://api.ads.apple.com/v1/acls`.",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="SEARCHADS.27478e17-...",
                        caption="Apple shows this after you save the public key for your API client.",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="apple_team_id",
                        label="Team ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="SEARCHADS.6f0a1b2c-...",
                        caption="Apple shows this next to the client ID. It often matches the client ID.",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="key_id",
                        label="Key ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="a1b2c3d4-...",
                        caption="Apple shows this next to the client ID.",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="private_key",
                        label="Private key",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="-----BEGIN EC PRIVATE KEY-----",
                        caption="The unencrypted EC P-256 private key matching the public key you uploaded to Apple.",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Report start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="2026-06-01",
                        caption="Earliest day to pull reporting for. Apple serves daily reporting for the last 90 days, so anything older is read from that day instead.",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="org_id",
                        label="Organization ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="123456",
                        caption="Only for sources still on Apple's Campaign Management API 5, which Apple stops serving on 26 January 2027. Leave this empty and enter an ad account ID instead.",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AppleSearchAdsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        endpoints = endpoints_for_version(self.resolve_api_version(api_version))
        schemas = build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            descriptions=ENDPOINT_DESCRIPTIONS,
            # Every incremental run re-reads a trailing window of already-imported days, so
            # these tables have to merge on their primary key; appending would duplicate rows.
            merge_only=REPORT_ENDPOINTS,
        )

        for schema in schemas:
            # Apple keeps revising the last few days of reporting data (ingestion delay plus
            # attribution), so an incremental run re-reads a trailing window instead of
            # trusting the frozen watermark.
            if endpoints[schema.name].partition_key is not None:
                schema.default_incremental_lookback_seconds = REPORT_LOOKBACK_SECONDS

        return schemas

    def validate_credentials(
        self,
        config: AppleSearchAdsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_apple_search_ads_credentials(
            self._credentials(config),
            self.resolve_api_version(api_version),
            schema_name,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AppleSearchAdsResumeConfig]:
        # Entity and report endpoints store incompatible checkpoint shapes, so keep each
        # endpoint's state in its own Redis slot.
        return ResumableSourceManager[AppleSearchAdsResumeConfig](inputs, AppleSearchAdsResumeConfig).with_namespace(
            inputs.schema_name
        )

    def source_for_pipeline(
        self,
        config: AppleSearchAdsSourceConfig,
        resumable_source_manager: ResumableSourceManager[AppleSearchAdsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return apple_search_ads_source(
            credentials=self._credentials(config),
            endpoint=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            request_logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            start_date=config.start_date,
        )

    @staticmethod
    def _credentials(config: AppleSearchAdsSourceConfig) -> AppleSearchAdsCredentials:
        return AppleSearchAdsCredentials(
            client_id=config.client_id,
            team_id=config.apple_team_id,
            key_id=config.key_id,
            private_key=config.private_key,
            org_id=config.org_id,
            ad_account_id=config.ad_account_id,
        )
