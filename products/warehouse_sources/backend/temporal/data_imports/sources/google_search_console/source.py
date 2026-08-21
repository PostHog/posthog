from typing import Optional, cast

import requests
from google.auth.exceptions import RefreshError

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldOauthAccountSelectConfig,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from posthog.exceptions_capture import capture_exception
from posthog.models.integration import Integration

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googlesearchconsole import (
    GoogleSearchConsoleSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.google_search_console import (
    GoogleSearchConsoleResumeConfig,
    google_search_console_session,
    google_search_console_source,
    list_sites,
    normalize_site_url,
    suggest_registered_site,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.settings import (
    DEFAULT_SEARCH_TYPE,
    PROPERTY_SCHEMAS,
    SEARCH_ANALYTICS_INCREMENTAL_FIELD,
    SEARCH_ANALYTICS_SCHEMAS,
    SEARCH_TYPES,
    SearchAnalyticsSchema,
    qualified_schema_name,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Fallback messages for unexpected failures during credential validation. The raw exception can
# embed OAuth tokens, ids, or an HTML error body, so we capture it for debugging and show generic
# guidance instead of surfacing `str(e)` to the user.
_LOAD_CONNECTION_ERROR = (
    "PostHog couldn't load your Google Search Console connection. Please reconnect your Google account and try again."
)
_LIST_SITES_ERROR = (
    "PostHog couldn't reach Google Search Console to list your properties. Please try again in a few minutes."
)


@SourceRegistry.register
class GoogleSearchConsoleSource(
    ResumableSource[GoogleSearchConsoleSourceConfig, GoogleSearchConsoleResumeConfig], OAuthMixin
):
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://developers.google.com/webmaster-tools"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLESEARCHCONSOLE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Google Search Console connection is invalid or expired. Please reconnect your account.",
            "403 Client Error": "PostHog is not authorized to read this Search Console property. Please make sure the connected Google account has access to the property.",
            "ACCESS_TOKEN_SCOPE_INSUFFICIENT": "Insufficient permissions. Please reconnect your Google Search Console account with the required scopes.",
            # `Integration.DoesNotExist` is raised by `_get_integration` when the source config still
            # references an OAuth integration row that has since been deleted (account disconnected).
            # No retry can recreate the row, so stop and ask the user to reconnect.
            "Integration matching query does not exist": "The Google Search Console connection for this source no longer exists. Please reconnect your Google account.",
            # `RefreshError: invalid_grant` is raised while AuthorizedSession refreshes the OAuth
            # access token — the stored refresh token has been revoked, expired, or invalidated
            # (app access revoked, password change, long inactivity). It never recovers on retry,
            # so stop the sync and ask the user to reconnect rather than burning activity retries.
            "invalid_grant": "Your Google Search Console connection has expired or been revoked. Please reconnect your account.",
        }

    def get_oauth_accounts(
        self, integration_id: int, team_id: int, search: str | None = None
    ) -> list[IntegrationAccount]:
        # Search Console sites are few, so `search` is ignored here and the endpoint filters the list.
        try:
            session = google_search_console_session(integration_id, team_id)
        except Integration.DoesNotExist:
            raise IntegrationAccountListingError(
                "The Google Search Console connection for this source no longer exists. "
                "Please reconnect your Google account."
            )
        try:
            sites = list_sites(session)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status in (401, 403):
                # The token refreshed fine but the connected Google account isn't authorized to read
                # Search Console — a customer-side connection issue. Surface an actionable message the
                # endpoint turns into a 400 rather than an unhandled 500.
                raise IntegrationAccountListingError(
                    "Google Search Console rejected the credentials. Please reconnect your account "
                    "and ensure it has read access to the property."
                )
            raise
        except RefreshError:
            # The stored OAuth token is revoked/expired/missing scopes — raised while AuthorizedSession
            # refreshes it. Not a server bug, so surface an actionable reconnect message (400) rather
            # than letting the raw RefreshError escape as a 500.
            raise IntegrationAccountListingError(
                "Could not authenticate with Google Search Console. Please reconnect the integration."
            )
        # GSC has no name distinct from the site url, so value and display_name are the same.
        return [
            IntegrationAccount(
                value=site["siteUrl"],
                display_name=site["siteUrl"],
                badges=(site["permissionLevel"],) if site.get("permissionLevel") else (),
            )
            for site in sites
        ]

    @staticmethod
    def effective_search_types(config: GoogleSearchConsoleSourceConfig) -> list[str]:
        """Search types to build tables for, in `SEARCH_TYPES` order.

        Falls back to web when unset, so sources created before this field existed keep
        exactly the table set they already sync.
        """
        selected = set(config.search_types or [])
        return [t for t in SEARCH_TYPES if t in selected] or [DEFAULT_SEARCH_TYPE]

    @staticmethod
    def _search_analytics_schema(base_name: str, schema: SearchAnalyticsSchema, search_type: str) -> SourceSchema:
        is_default_type = search_type == DEFAULT_SEARCH_TYPE
        description = schema["description"]
        if not is_default_type and description is not None:
            description = f"{description} Restricted to {search_type} search results."
        return SourceSchema(
            name=qualified_schema_name(base_name, search_type),
            supports_incremental=True,
            supports_append=True,
            incremental_fields=[SEARCH_ANALYTICS_INCREMENTAL_FIELD],
            description=description,
            # Never default-on a non-web table: each one costs a full history backfill,
            # and picking a search type shouldn't silently start one.
            should_sync_default=schema["should_sync_default"] and is_default_type,
        )

    def get_schemas(
        self,
        config: GoogleSearchConsoleSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            self._search_analytics_schema(base_name, schema, search_type)
            for search_type in self.effective_search_types(config)
            for base_name, schema in SEARCH_ANALYTICS_SCHEMAS.items()
            if search_type == DEFAULT_SEARCH_TYPE or not schema.get("web_only")
        ]
        # Property metadata is a full snapshot each sync: both endpoints return the current
        # state with no timestamp to filter on, so there is nothing to sync incrementally.
        schemas += [
            SourceSchema(
                name=name,
                supports_incremental=False,
                supports_append=False,
                description=property_schema["description"],
                should_sync_default=property_schema["should_sync_default"],
            )
            for name, property_schema in PROPERTY_SCHEMAS.items()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[GoogleSearchConsoleResumeConfig]:
        return ResumableSourceManager[GoogleSearchConsoleResumeConfig](inputs, GoogleSearchConsoleResumeConfig)

    def source_for_pipeline(
        self,
        config: GoogleSearchConsoleSourceConfig,
        resumable_source_manager: ResumableSourceManager[GoogleSearchConsoleResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return google_search_console_source(
            config=config,
            resource_name=inputs.schema_name,
            team_id=inputs.team_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    def validate_credentials(
        self,
        config: GoogleSearchConsoleSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            session = google_search_console_session(config.google_search_console_integration_id, team_id)
        except Integration.DoesNotExist:
            return (
                False,
                "The Google Search Console connection for this source no longer exists. Please reconnect your Google account.",
            )
        except Exception as e:
            if "matching query does not exist" in str(e):
                return False, (
                    "Your Google Search Console connection is no longer available. It may have been "
                    "disconnected. Please reconnect your Google Search Console account."
                )
            capture_exception(e)
            return False, _LOAD_CONNECTION_ERROR

        try:
            sites = list_sites(session)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status in (401, 403):
                return (
                    False,
                    "Google Search Console rejected the credentials. Please reconnect your account and ensure it has read access to the property.",
                )
            capture_exception(e)
            return False, _LIST_SITES_ERROR
        except RefreshError:
            # Raised while AuthorizedSession refreshes the OAuth access token (e.g. invalid_scope or
            # invalid_grant): the stored token is missing the required permissions, or has expired or
            # been revoked. Retrying can't recover it — the raw RefreshError repr is meaningless to
            # users, so guide them to reconnect.
            return (
                False,
                "PostHog could not authenticate with Google Search Console. Your connection may have "
                "expired or is missing the required permissions. Please reconnect your Google account "
                "and grant access to Search Console.",
            )
        except Exception as e:
            capture_exception(e)
            return False, _LIST_SITES_ERROR

        normalized = {url: site.get("permissionLevel") for site in sites if (url := site.get("siteUrl")) is not None}
        site_url = normalize_site_url(config.site_url)
        if site_url not in normalized:
            suggestion = suggest_registered_site(site_url, normalized.keys())
            if suggestion is not None:
                return (
                    False,
                    f"'{site_url}' isn't a Search Console property, but the connected account has "
                    f"'{suggestion}'. Enter the property exactly as Search Console lists it — '{suggestion}' — "
                    f"and try again.",
                )
            return (
                False,
                f"Site '{site_url}' is not visible to the connected Google account. Verify the property URL "
                f"(e.g. 'https://example.com/' or 'sc-domain:example.com') and that the account has access.",
            )
        permission = normalized[site_url]
        if permission == "siteUnverifiedUser":
            return (
                False,
                f"The connected Google account does not have verified access to '{site_url}'. "
                f"Verify the property in Search Console and try again.",
            )
        return True, None

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GOOGLE_SEARCH_CONSOLE,
            category=DataWarehouseSourceCategory.ANALYTICS,
            keywords=["gsc", "seo", "search analytics", "organic search"],
            label="Google Search Console",
            caption=(
                "Connect a verified Google Search Console property to sync daily Search Analytics performance data "
                "(clicks, impressions, CTR, average position). Requires a Google account with read access to the property."
            ),
            releaseStatus=ReleaseStatus.GA,
            iconPath="/static/services/google-search-console.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/google-search-console",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="google_search_console_integration_id",
                        label="Google Search Console account",
                        required=True,
                        kind="google-search-console",
                    ),
                    SourceFieldOauthAccountSelectConfig(
                        name="site_url",
                        label="Property URL",
                        integrationField="google_search_console_integration_id",
                        integrationKind="google-search-console",
                        placeholder="https://example.com/ or sc-domain:example.com",
                        caption=(
                            "The exact verified property URL as it appears in Google Search Console. "
                            "Use the trailing slash for URL prefix properties or the `sc-domain:` prefix for domain properties."
                        ),
                        required=True,
                    ),
                    SourceFieldSelectConfig(
                        name="search_types",
                        label="Search types",
                        required=True,
                        defaultValue=DEFAULT_SEARCH_TYPE,
                        multiple=True,
                        options=[
                            SourceFieldSelectConfigOption(label="Web", value="web"),
                            SourceFieldSelectConfigOption(label="Image", value="image"),
                            SourceFieldSelectConfigOption(label="Video", value="video"),
                            SourceFieldSelectConfigOption(label="News", value="news"),
                        ],
                        caption=(
                            "Which Search Console result types to sync. Web keeps the original table names. "
                            "Every other type adds a copy of each table with the type as a suffix, such as "
                            "search_analytics_by_page_image, and each copy costs a full set of API requests. "
                            "Removing a type later stops its tables syncing, but keeps the data already imported."
                        ),
                    ),
                ],
            ),
        )
