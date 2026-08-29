from typing import Optional, cast

import requests
from google.auth.exceptions import RefreshError

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googletagmanager import (
    GoogleTagManagerSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_tag_manager.google_tag_manager import (
    get_accounts_probe,
    google_tag_manager_session,
    google_tag_manager_source,
    parse_account_ids,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_tag_manager.settings import ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GoogleTagManagerSource(SimpleSource[GoogleTagManagerSourceConfig], OAuthMixin):
    # The request layer calls /tagmanager/v2/ paths, the current GA version of the API.
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developers.google.com/tag-platform/tag-manager/api/v2"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLETAGMANAGER

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.google_tag_manager.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "missing a refresh token": "Your Google Tag Manager connection is incomplete. Please reconnect your Google account.",
            "401 Client Error": "Your Google Tag Manager connection is invalid or expired. Please reconnect your account.",
            "403 Client Error": "PostHog is not authorized to read from this Google Tag Manager account. Make sure the connected Google user has at least read access to the account.",
            "ACCESS_TOKEN_SCOPE_INSUFFICIENT": "Insufficient permissions. Please reconnect your Google Tag Manager account and grant read access to Tag Manager.",
            # Raised as a bare `RefreshError` from `AuthorizedSession` when the stored refresh token
            # has been revoked or expired. Mid-sync it surfaces before any HTTP status is available
            # to match on, so match Google's stable OAuth error code instead.
            "invalid_grant": "Your Google Tag Manager connection has expired or been revoked. Please reconnect your account.",
        }

    def get_retryable_errors(self) -> set[str]:
        # The transport already retries quota exhaustion in-line with backoff; the GTM quota is
        # shared per project and refills over time, so when retries run out let Temporal retry
        # the sync later without paging it as a bug.
        return {"(retryable)"}

    def get_schemas(
        self,
        config: GoogleTagManagerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # The GTM API has no server-side modification-time filter, so every table is full
        # refresh only. The tables are configuration objects and stay small.
        schemas = [
            SourceSchema(
                name=endpoint.name,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                description=endpoint.description,
            )
            for endpoint in ENDPOINTS.values()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def _refresh_token(self, integration_id: int, team_id: int) -> str:
        integration = self.get_oauth_integration(integration_id, team_id)
        if not integration.refresh_token:
            raise ValueError("The Google Tag Manager connection is missing a refresh token")
        return integration.refresh_token

    def source_for_pipeline(self, config: GoogleTagManagerSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return google_tag_manager_source(
            config=config,
            resource_name=inputs.schema_name,
            refresh_token=self._refresh_token(config.google_tag_manager_integration_id, inputs.team_id),
        )

    def validate_credentials(
        self,
        config: GoogleTagManagerSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            refresh_token = self._refresh_token(config.google_tag_manager_integration_id, team_id)
        except ValueError:
            # The stored OAuth integration row has been deleted, disconnected, or stripped of its
            # refresh token before validation runs.
            return (
                False,
                "The Google Tag Manager connection for this source no longer exists. Please reconnect your Google account.",
            )
        except Exception as e:
            return False, f"Could not load Google Tag Manager credentials: {e}"

        try:
            payload = get_accounts_probe(google_tag_manager_session(refresh_token))
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status in (401, 403):
                return (
                    False,
                    "Google Tag Manager rejected the credentials. Please reconnect your Google account and grant read access to Tag Manager.",
                )
            return False, f"Failed to list Google Tag Manager accounts: {e}"
        except RefreshError:
            # Raised while AuthorizedSession refreshes the OAuth access token (e.g. invalid_scope or
            # invalid_grant): the stored token is missing the required permissions, or has expired or
            # been revoked. Retrying can't recover it, and the raw RefreshError repr is meaningless
            # to users, so guide them to reconnect.
            return (
                False,
                "PostHog could not authenticate with Google Tag Manager. Your connection may have "
                "expired or is missing the required permissions. Please reconnect your Google "
                "account and grant read access to Tag Manager.",
            )
        except Exception as e:
            return False, f"Failed to list Google Tag Manager accounts: {e}"

        accessible_ids = {account.get("accountId") for account in payload.get("account") or []}
        if not accessible_ids:
            return (
                False,
                "The connected Google user doesn't have access to any Tag Manager accounts. "
                "Connect a Google user with at least read access to the accounts you want to sync.",
            )

        # Only enforce the filter when the probe saw the full account list; with more pages the
        # missing IDs may simply be on a later page.
        account_ids = parse_account_ids(config.account_ids)
        if account_ids is not None and not payload.get("nextPageToken"):
            missing = sorted(account_ids - accessible_ids)
            if missing:
                return (
                    False,
                    f"The connected Google user can't access these Tag Manager account IDs: {', '.join(missing)}. "
                    "Check the IDs in Tag Manager under Admin, or leave the field blank to sync every accessible account.",
                )

        return True, None

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GOOGLE_TAG_MANAGER,
            category=DataWarehouseSourceCategory.ANALYTICS,
            keywords=["gtm", "tag manager"],
            label="Google Tag Manager",
            caption=(
                "Sync your Google Tag Manager setup (accounts, containers, workspaces, tags, triggers, "
                "variables, and container versions) into the PostHog data warehouse. Requires a Google "
                "user with at least read access to the Tag Manager accounts you want to sync."
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
                    SourceFieldInputConfig(
                        name="account_ids",
                        label="Account IDs",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="6000000001, 6000000002",
                        caption=(
                            "Comma-separated Tag Manager account IDs to sync, found in Tag Manager "
                            "under Admin. Leave blank to sync every account the connected Google "
                            "user can access."
                        ),
                        secret=False,
                    ),
                ],
            ),
        )
