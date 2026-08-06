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
)

from posthog.exceptions_capture import capture_exception
from posthog.models.integration import Integration

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccount,
    IntegrationAccountListingError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googletagmanager import (
    GoogleTagManagerSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_tag_manager.google_tag_manager import (
    google_tag_manager_session,
    google_tag_manager_source,
    list_accounts,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_tag_manager.settings import GTM_SCHEMAS
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Fallback messages for unexpected failures during credential validation. The raw exception can
# embed OAuth tokens, ids, or an HTML error body, so we capture it for debugging and show generic
# guidance instead of surfacing `str(e)` to the user.
_LOAD_CONNECTION_ERROR = (
    "PostHog couldn't load your Google Tag Manager connection. Please reconnect your Google account and try again."
)
_LIST_ACCOUNTS_ERROR = (
    "PostHog couldn't reach Google Tag Manager to list your accounts. Please try again in a few minutes."
)


@SourceRegistry.register
class GoogleTagManagerSource(SimpleSource[GoogleTagManagerSourceConfig], OAuthMixin):
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developers.google.com/tag-platform/tag-manager/api/v2"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLETAGMANAGER

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Google Tag Manager connection is invalid or expired. Please reconnect your account.",
            "403 Client Error": "PostHog is not authorized to read this Tag Manager account. Please make sure the connected Google account has access to it.",
            "ACCESS_TOKEN_SCOPE_INSUFFICIENT": "Insufficient permissions. Please reconnect your Google Tag Manager account with the required scopes.",
            # `Integration.DoesNotExist` is raised when the source config references an OAuth
            # integration row that has since been deleted (account disconnected). No retry can
            # recreate it, so stop and ask the user to reconnect.
            "Integration matching query does not exist": "The Google Tag Manager connection for this source no longer exists. Please reconnect your Google account.",
            # `RefreshError: invalid_grant` means the stored refresh token was revoked or expired.
            # It never recovers on retry, so stop the sync and ask the user to reconnect.
            "invalid_grant": "Your Google Tag Manager connection has expired or been revoked. Please reconnect your account.",
        }

    def get_oauth_accounts(
        self, integration_id: int, team_id: int, search: str | None = None
    ) -> list[IntegrationAccount]:
        # Accounts are few, so `search` is ignored here and the endpoint filters the list.
        try:
            session = google_tag_manager_session(integration_id, team_id)
        except Integration.DoesNotExist:
            raise IntegrationAccountListingError(
                "The Google Tag Manager connection for this source no longer exists. "
                "Please reconnect your Google account."
            )
        try:
            accounts = list_accounts(session)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status in (401, 403):
                raise IntegrationAccountListingError(
                    "Google Tag Manager rejected the credentials. Please reconnect your account "
                    "and ensure it has access to at least one account."
                )
            raise
        except RefreshError:
            raise IntegrationAccountListingError(
                "Could not authenticate with Google Tag Manager. Please reconnect the integration."
            )
        return [
            IntegrationAccount(
                value=account["accountId"],
                display_name=account.get("name") or account["accountId"],
                secondary_text=account["accountId"],
            )
            for account in accounts
            if account.get("accountId")
        ]

    def get_schemas(
        self,
        config: GoogleTagManagerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Tag Manager exposes no server-side timestamp filter on any list endpoint, so every table
        # is a full-refresh snapshot of the current configuration — nothing to sync incrementally.
        schemas = [
            SourceSchema(
                name=name,
                supports_incremental=False,
                supports_append=False,
                description=schema["description"],
                should_sync_default=schema["should_sync_default"],
            )
            for name, schema in GTM_SCHEMAS.items()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.google_tag_manager.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def source_for_pipeline(self, config: GoogleTagManagerSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return google_tag_manager_source(
            config=config,
            resource_name=inputs.schema_name,
            team_id=inputs.team_id,
        )

    def validate_credentials(
        self,
        config: GoogleTagManagerSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            session = google_tag_manager_session(config.google_tag_manager_integration_id, team_id)
        except Integration.DoesNotExist:
            return (
                False,
                "The Google Tag Manager connection for this source no longer exists. Please reconnect your Google account.",
            )
        except Exception as e:
            if "matching query does not exist" in str(e):
                return False, (
                    "Your Google Tag Manager connection is no longer available. It may have been "
                    "disconnected. Please reconnect your Google Tag Manager account."
                )
            capture_exception(e)
            return False, _LOAD_CONNECTION_ERROR

        try:
            accounts = list_accounts(session)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status in (401, 403):
                return (
                    False,
                    "Google Tag Manager rejected the credentials. Please reconnect your account and ensure it has access to the account.",
                )
            capture_exception(e)
            return False, _LIST_ACCOUNTS_ERROR
        except RefreshError:
            return (
                False,
                "PostHog could not authenticate with Google Tag Manager. Your connection may have "
                "expired or is missing the required permissions. Please reconnect your Google account "
                "and grant access to Tag Manager.",
            )
        except Exception as e:
            capture_exception(e)
            return False, _LIST_ACCOUNTS_ERROR

        account_ids = {account.get("accountId") for account in accounts}
        if config.account_id not in account_ids:
            return (
                False,
                f"Account '{config.account_id}' is not visible to the connected Google account. "
                f"Verify the account and that the connected account has access to it.",
            )
        return True, None

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GOOGLE_TAG_MANAGER,
            category=DataWarehouseSourceCategory.ANALYTICS,
            keywords=["gtm", "tag manager", "tags", "containers"],
            label="Google Tag Manager",
            caption=(
                "Connect a Google Tag Manager account to sync its containers, workspaces, tags, triggers, "
                "variables, and container versions. Requires a Google account with access to the Tag Manager account."
            ),
            releaseStatus=ReleaseStatus.ALPHA,
            iconPath="/static/services/google-tag-manager.png",
            docsUrl="https://posthog.com/docs/cdp/sources/google-tag-manager",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="google_tag_manager_integration_id",
                        label="Google Tag Manager account",
                        required=True,
                        kind="google-tag-manager",
                        requiredScopes="https://www.googleapis.com/auth/tagmanager.readonly",
                    ),
                    SourceFieldOauthAccountSelectConfig(
                        name="account_id",
                        label="Account",
                        integrationField="google_tag_manager_integration_id",
                        integrationKind="google-tag-manager",
                        placeholder="Select a Tag Manager account",
                        required=True,
                    ),
                ],
            ),
        )
