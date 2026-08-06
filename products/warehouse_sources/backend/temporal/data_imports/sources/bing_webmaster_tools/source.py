from typing import Optional, cast

import requests

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools.bing_webmaster_tools import (
    BingWebmasterToolsError,
    bing_session,
    bing_webmaster_tools_source,
    list_user_sites,
    normalize_site_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools.settings import (
    DATE_INCREMENTAL_FIELD,
    ENDPOINTS,
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

# Generic fallback for an unexpected failure while validating. The raw exception can embed the
# request URL, which carries the API key in a query param, so we capture it for debugging and show
# guidance instead of surfacing `str(e)` to the user.
_VALIDATION_ERROR = "PostHog couldn't reach Bing Webmaster Tools. Please check your API key and site URL and try again."


@SourceRegistry.register
class BingWebmasterToolsSource(SimpleSource[BingWebmasterToolsSourceConfig]):
    # Bing's JSON API has no version segment or version header — it's a single unversioned
    # surface — so the version metadata stays at the framework default and only `api_docs_url` is set.
    api_docs_url = "https://learn.microsoft.com/en-us/bingwebmaster/api-protocols"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BINGWEBMASTERTOOLS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Bing Webmaster Tools API key is invalid or expired. Generate a new key in Bing Webmaster Tools and reconnect.",
            "403 Client Error": "Your Bing Webmaster Tools API key is not authorized for this site. Check that the key's account has access to the property.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools.canonical_descriptions import (
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
                supports_incremental=True,
                supports_append=True,
                incremental_fields=[DATE_INCREMENTAL_FIELD],
                description=endpoint["description"],
                should_sync_default=endpoint["should_sync_default"],
                detected_primary_keys=list(endpoint["primary_key"]),
            )
            for name, endpoint in ENDPOINTS.items()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def source_for_pipeline(self, config: BingWebmasterToolsSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return bing_webmaster_tools_source(
            config=config,
            resource_name=inputs.schema_name,
            team_id=inputs.team_id,
        )

    def validate_credentials(
        self,
        config: BingWebmasterToolsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        session = bing_session(config.api_key)
        try:
            sites = list_user_sites(session, config.api_key)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status in (401, 403):
                return (
                    False,
                    "Bing Webmaster Tools rejected the API key. Generate a key in Bing Webmaster Tools under "
                    "Settings → API access and make sure its account has access to the site.",
                )
            capture_exception(e)
            return False, _VALIDATION_ERROR
        except BingWebmasterToolsError as e:
            capture_exception(e)
            return False, _VALIDATION_ERROR
        except Exception as e:
            capture_exception(e)
            return False, _VALIDATION_ERROR

        registered = {normalize_site_url(url) for site in sites if (url := site.get("Url")) is not None}
        if normalize_site_url(config.site_url) not in registered:
            return (
                False,
                f"'{config.site_url}' is not a verified site on this Bing Webmaster Tools account. Add and verify "
                "the site in Bing Webmaster Tools, then enter its URL exactly as it appears there.",
            )
        return True, None

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BING_WEBMASTER_TOOLS,
            category=DataWarehouseSourceCategory.ANALYTICS,
            keywords=["bing", "yahoo", "seo", "webmaster", "search analytics", "organic search"],
            label="Microsoft (Bing Webmaster Tools)",
            caption=(
                "Sync organic-search performance for a site verified in Bing Webmaster Tools (Bing and Yahoo search). "
                "Create an API key under **Settings → API access** in Bing Webmaster Tools and enter it below."
            ),
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
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="site_url",
                        label="Site URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://example.com",
                        secret=False,
                    ),
                ],
            ),
        )
