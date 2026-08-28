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
    APPLE_SEARCH_ADS_ENDPOINTS,
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    REPORT_ENDPOINTS,
    REPORT_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
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

    supported_versions = ("v5",)
    default_version = "v5"
    api_docs_url = "https://developer.apple.com/documentation/apple_search_ads"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.APPLESEARCHADS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "400 Client Error: Bad Request for url: https://appleid.apple.com/auth/oauth2/token": "Apple rejected the signed client secret. Check your client ID, team ID, key ID and private key.",
            "401 Client Error: Unauthorized for url: https://appleid.apple.com/auth/oauth2/token": "Apple rejected the signed client secret. Check your client ID, team ID, key ID and private key.",
            "401 Client Error: Unauthorized for url: https://api.searchads.apple.com": "Apple Search Ads rejected the access token. Your API key may have been revoked — generate a new one and reconnect.",
            "403 Client Error: Forbidden for url: https://api.searchads.apple.com": "Apple Search Ads denied access to this organization. Check that the API user has at least read access to the organization ID you entered.",
            "Could not sign the Apple Search Ads client secret": "The private key isn't a valid unencrypted EC (P-256) PEM. Paste the key you generated for your Search Ads API key and reconnect.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.APPLE_SEARCH_ADS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Apple Search Ads",
            caption="""Connect your Apple Search Ads account to pull campaigns, ad groups, keywords and daily performance into the PostHog Data warehouse.

In the Search Ads UI, create an API user with at least **Read only** access, generate an API key, and keep the private key it gives you. Then enter the organization ID, client ID, team ID and key ID from the API key page, plus the private key itself. PostHog signs a short-lived token with the key on every sync, so no long-lived secret is stored.""",
            iconPath="/static/services/apple_search_ads.png",
            docsUrl="https://posthog.com/docs/cdp/sources/apple-search-ads",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["asa", "app store ads", "search ads"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="org_id",
                        label="Organization ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="123456",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="SEARCHADS.27478e17-...",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="apple_team_id",
                        label="Team ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="SEARCHADS.27478e17-...",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="key_id",
                        label="Key ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="a1b2c3d4-...",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="private_key",
                        label="Private key",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="-----BEGIN EC PRIVATE KEY-----",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Report start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="2024-01-01",
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
            if APPLE_SEARCH_ADS_ENDPOINTS[schema.name].partition_key is not None:
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
            org_id=config.org_id,
            client_id=config.client_id,
            team_id=config.apple_team_id,
            key_id=config.key_id,
            private_key=config.private_key,
        )
