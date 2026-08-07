from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools.bing_webmaster_tools import (
    bing_webmaster_tools_source,
    validate_credentials as validate_bing_webmaster_tools_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools.settings import (
    ENDPOINT_CONFIGS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bingwebmastertools import (
    BingWebmasterToolsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BingWebmasterToolsSource(SimpleSource[BingWebmasterToolsSourceConfig]):
    # `get_schemas` iterates a static endpoint catalog with no I/O, so the table list is safe to
    # render in public docs without credentials.
    lists_tables_without_credentials = True
    # The JSON API (`/webmaster/api.svc/json`) has no version path segment, version header, or dated
    # releases, so the framework's unversioned default stands.
    api_docs_url = "https://learn.microsoft.com/en-us/bingwebmaster/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BINGWEBMASTERTOOLS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # ApiFault messages (surfaced by `BingWebmasterToolsError`) for credential and access
        # problems are deterministic; throttling faults deliberately stay unmatched so Temporal
        # retries them at the activity level.
        return {
            "InvalidApiKey": "Your Bing Webmaster Tools API key is invalid. Generate a new key under Settings > API access in Bing Webmaster Tools, then reconnect.",
            "UserNotFound": "Bing Webmaster Tools did not recognize the API key. Generate a new key under Settings > API access in Bing Webmaster Tools, then reconnect.",
            "NotAuthorized": "The API key does not have access to this site. Make sure the site is verified on the connected Bing Webmaster Tools account.",
            "401 Client Error": "Your Bing Webmaster Tools API key is invalid or expired. Generate a new key and reconnect.",
            "403 Client Error": "Your Bing Webmaster Tools API key does not have access to this site. Verify the site on the connected account and reconnect.",
            # Fault-less 400s carry the redacted request URL; a 400 from this API is a deterministic
            # rejection of the key or the requested site, not a transient failure.
            "400 Client Error: Bad Request for url: https://ssl.bing.com": "Bing Webmaster Tools rejected the request. Check that the API key is valid and that the connected account can access the configured sites.",
            # A site filter naming a site the account can't see fails every sync until the config
            # changes; the raised message already tells the user how to fix it.
            "not verified sites on the connected account": None,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools.canonical_descriptions import (  # noqa: PLC0415 (keeps the descriptions dict off the registry import path; only the enrichment activity reads it)
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: BingWebmasterToolsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=name,
                # The API has no server-side time filter, so every sync refetches the ~6-month
                # window Bing retains. "Incremental" here means merge-on-primary-key, which keeps
                # rows the vendor has already expired. Append is unsupported because refetching the
                # same window would duplicate it on every sync.
                supports_incremental=bool(endpoint.incremental_fields),
                supports_append=False,
                incremental_fields=endpoint.incremental_fields,
                description=endpoint.description,
                should_sync_default=endpoint.should_sync_default,
            )
            for name, endpoint in ENDPOINT_CONFIGS.items()
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: BingWebmasterToolsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_bing_webmaster_tools_credentials(config.api_key, config.site_urls)

    def source_for_pipeline(self, config: BingWebmasterToolsSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return bing_webmaster_tools_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            site_urls_raw=config.site_urls,
            logger=inputs.logger,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BING_WEBMASTER_TOOLS,
            category=DataWarehouseSourceCategory.ANALYTICS,
            keywords=["bing", "seo", "organic search", "search analytics"],
            label="Bing Webmaster Tools",
            caption="""Sync your site's organic search performance on Bing into the PostHog Data warehouse: top queries, top pages, daily rank and traffic, and crawl statistics.

Generate an API key in [Bing Webmaster Tools](https://www.bing.com/webmasters) under **Settings > API access > API key**. The key is issued per user and covers every verified site on the account.
""",
            releaseStatus=ReleaseStatus.ALPHA,
            iconPath="/static/services/bing_webmaster_tools.png",
            docsUrl="https://posthog.com/docs/cdp/sources/bing-webmaster-tools",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Your Bing Webmaster Tools API key",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="site_urls",
                        label="Site URLs",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=False,
                        placeholder="https://example.com/",
                        secret=False,
                        caption=(
                            "Optional. One site per line, exactly as Bing Webmaster Tools lists it. "
                            "Leave empty to sync every verified site on the account."
                        ),
                    ),
                ],
            ),
        )
