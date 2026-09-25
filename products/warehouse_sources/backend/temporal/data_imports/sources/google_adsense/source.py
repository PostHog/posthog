from typing import Optional, cast

from django.core.cache import cache

import requests
from google.auth.exceptions import RefreshError

from posthog.exceptions_capture import capture_exception
from posthog.models.integration import Integration

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthAccountSelectConfig,
    SourceFieldOauthConfig,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googleadsense import (
    GoogleAdSenseSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_adsense.google_adsense import (
    DEFAULT_INCREMENTAL_LOOKBACK_SECONDS,
    GoogleAdSenseResumeConfig,
    _coerce_date,
    _is_quota_error,
    get_account,
    google_adsense_session,
    google_adsense_source,
    list_accounts,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_adsense.settings import (
    ENTITY_SCHEMAS,
    REPORTS_INCREMENTAL_FIELD,
    REPORTS_SCHEMAS,
    ReportsSchema,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Fallback messages for unexpected failures during credential validation. The raw exception can
# embed OAuth tokens, ids, or an HTML error body, so we capture it for debugging and show generic
# guidance instead of surfacing `str(e)` to the user.
_LOAD_CONNECTION_ERROR = (
    "PostHog couldn't load your Google AdSense connection. Please reconnect your Google account and try again."
)

_LIST_ACCOUNTS_ERROR = "PostHog couldn't reach Google AdSense to list your accounts. Please try again in a few minutes."

# Listing accounts fails at least four ways, and Google reports several of them as a 403:
# an exhausted quota, an account with no read access to any AdSense account, a token that
# no longer works, and the AdSense API being disabled on this project (reason
# SERVICE_DISABLED). Telling a user to reconnect only fixes the token case — a disabled-API
# 403 is an ops-level project misconfiguration, not something a reconnect prompt resolves.
_ACCOUNT_LIST_QUOTA_ERROR = "Google is rate limiting AdSense requests. Wait a minute, then try again."
_ACCOUNT_LIST_ACCESS_ERROR = (
    "The connected Google account can't read any AdSense account. Reconnect and allow "
    "AdSense access, or use the account that owns the AdSense account."
)
_ACCOUNT_LIST_CREDENTIALS_ERROR = (
    "Google rejected the credentials for this connection. Reconnect your Google account, then pick an account."
)

_OAUTH_ACCOUNTS_CACHE_TTL_SECONDS = 60


def _account_list_http_error(error: requests.HTTPError) -> str:
    response = error.response
    if response is not None and _is_quota_error(response):
        return _ACCOUNT_LIST_QUOTA_ERROR
    if response is not None and response.status_code == 403:
        return _ACCOUNT_LIST_ACCESS_ERROR
    return _ACCOUNT_LIST_CREDENTIALS_ERROR


def _oauth_accounts_cache_key(team_id: int, integration_id: int) -> str:
    # Keyed on (team, integration) only — never the search term — so distinct searches share one walk.
    return f"@dwh/google_adsense/{team_id}/{integration_id}/oauth_accounts"


@SourceRegistry.register
class GoogleAdSenseSource(ResumableSource[GoogleAdSenseSourceConfig, GoogleAdSenseResumeConfig], OAuthMixin):
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developers.google.com/adsense/management/reference/rest"
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEADSENSE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Google AdSense connection is invalid or expired. Please reconnect your account.",
            "403 Client Error": "PostHog is not authorized to read this AdSense account. Please make sure the connected Google account has access to the account.",
            "ACCESS_TOKEN_SCOPE_INSUFFICIENT": "Insufficient permissions. Please reconnect your Google AdSense account with the required scopes.",
            # `Integration.DoesNotExist` is raised by `_get_integration` when the source config still
            # references an OAuth integration row that has since been deleted (account disconnected).
            # No retry can recreate the row, so stop and ask the user to reconnect.
            "Integration matching query does not exist": "The Google AdSense connection for this source no longer exists. Please reconnect your Google account.",
            # `RefreshError: invalid_grant` is raised while AuthorizedSession refreshes the OAuth
            # access token — the stored refresh token has been revoked, expired, or invalidated
            # (app access revoked, password change, long inactivity). It never recovers on retry,
            # so stop the sync and ask the user to reconnect rather than burning activity retries.
            "invalid_grant": "Your Google AdSense connection has expired or been revoked. Please reconnect your account.",
            "access_not_configured": "Your Google Workspace administrator has restricted API access for this app. Ask your admin to approve it, then reconnect your Google AdSense account.",
        }

    def get_retryable_errors(self) -> set[str]:
        # `_query_reports` already retries AdSense quota exhaustion in-line with backoff — both the
        # request-rate 403s (`usageLimits`/RATE_LIMIT_EXCEEDED) and the separate report-row 429 quota;
        # if it stays exhausted once those retries run out, the account's quota refills over time and
        # the resumable source picks up from the last saved date and row, so let Temporal retry the
        # activity without paging it as a bug. The quota raise sites carry a stable `(retryable)`
        # marker, which does not collide with the 401/403 non-retryable keys.
        return {"(retryable)"}

    def get_oauth_accounts(
        self, integration_id: int, team_id: int, search: str | None = None
    ) -> list[IntegrationAccount]:
        cache_key = _oauth_accounts_cache_key(team_id, integration_id)
        cached = cache.get(cache_key)

        if cached is not None:
            return cached

        try:
            session = google_adsense_session(integration_id, team_id)
        except Integration.DoesNotExist:
            raise IntegrationAccountListingError(
                "The Google AdSense connection for this source no longer exists. Please reconnect your Google account."
            )
        try:
            accounts = list_accounts(session)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status in (401, 403):
                # The token refreshed fine but Google still refused the listing — a customer-side
                # connection issue. Surface an actionable message the endpoint turns into a 400
                # rather than an unhandled 500.
                raise IntegrationAccountListingError(_account_list_http_error(e))
            raise
        except RefreshError:
            # The stored OAuth token is revoked/expired/missing scopes — raised while AuthorizedSession
            # refreshes it. Not a server bug, so surface an actionable reconnect message (400) rather
            # than letting the raw RefreshError escape as a 500.
            raise IntegrationAccountListingError(
                "Could not authenticate with Google AdSense. Please reconnect the integration."
            )

        result = [
            IntegrationAccount(
                value=account["name"],
                display_name=account["displayName"],
                badges=(account["state"],) if account.get("state") else (),
            )
            for account in accounts
        ]

        # Don't cache an empty result: a transient walk that returns [] without raising would otherwise
        # freeze the picker empty for the whole TTL for every admin on the team.
        if result:
            cache.set(cache_key, result, _OAUTH_ACCOUNTS_CACHE_TTL_SECONDS)

        return result

    def validate_credentials(
        self,
        config: GoogleAdSenseSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if config.start_date:
            try:
                _coerce_date(config.start_date)
            except (ValueError, TypeError):
                return False, "Start date must be a valid date in YYYY-MM-DD format (e.g. 2024-01-31)."

        try:
            session = google_adsense_session(config.google_adsense_integration_id, team_id)
        except Integration.DoesNotExist:
            return (
                False,
                "The Google AdSense connection for this source no longer exists. Please reconnect your Google account.",
            )
        except Exception as e:
            if "matching query does not exist" in str(e):
                return False, (
                    "Your Google AdSense connection is no longer available. It may have been "
                    "disconnected. Please reconnect your Google AdSense account."
                )
            capture_exception(e)
            return False, _LOAD_CONNECTION_ERROR

        try:
            account = get_account(session, config.account)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status in (401, 403):
                # The token refreshed fine but Google still refused the listing — a customer-side
                # connection issue. Surface an actionable message the endpoint turns into a 400
                # rather than an unhandled 500.
                return False, _account_list_http_error(e)
            capture_exception(e)
            return False, _LIST_ACCOUNTS_ERROR
        except RefreshError:
            # Raised while AuthorizedSession refreshes the OAuth access token (e.g. invalid_scope or
            # invalid_grant): the stored token is missing the required permissions, or has expired or
            # been revoked. Retrying can't recover it — the raw RefreshError repr is meaningless to
            # users, so guide them to reconnect.
            return False, (
                "PostHog could not authenticate with Google AdSense. Your connection may have expired or is missing "
                "the required permissions. Please reconnect your Google account and grant access to AdSense."
            )
        except Exception as e:
            capture_exception(e)
            return False, _LIST_ACCOUNTS_ERROR

        if account.get("state") and account["state"] != "READY":
            return False, _ACCOUNT_LIST_ACCESS_ERROR

        return True, None

    def get_schemas(
        self,
        config: GoogleAdSenseSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [self._reports_schema(base_name, schema) for base_name, schema in REPORTS_SCHEMAS.items()]

        # Entity metadata is a full snapshot each sync: these endpoints return the current
        # account/inventory state with no timestamp to filter on, so there is nothing to sync
        # incrementally.
        schemas += [
            SourceSchema(
                name=name,
                supports_incremental=False,
                supports_append=False,
                description=entity_schema["description"],
                should_sync_default=entity_schema["should_sync_default"],
            )
            for name, entity_schema in ENTITY_SCHEMAS.items()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.google_adsense.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    @staticmethod
    def _reports_schema(base_name: str, schema: ReportsSchema) -> SourceSchema:
        return SourceSchema(
            name=base_name,
            supports_incremental=True,
            supports_append=True,
            incremental_fields=[REPORTS_INCREMENTAL_FIELD],
            default_incremental_lookback_seconds=DEFAULT_INCREMENTAL_LOOKBACK_SECONDS,
            description=schema["description"],
            should_sync_default=schema["should_sync_default"],
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GoogleAdSenseResumeConfig]:
        return ResumableSourceManager[GoogleAdSenseResumeConfig](inputs, GoogleAdSenseResumeConfig)

    def source_for_pipeline(
        self,
        config: GoogleAdSenseSourceConfig,
        resumable_source_manager: ResumableSourceManager[GoogleAdSenseResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return google_adsense_source(
            config=config,
            resource_name=inputs.schema_name,
            team_id=inputs.team_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            db_incremental_field_last_value_before_lookback=inputs.db_incremental_field_last_value_before_lookback
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOOGLEADSENSE,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Google AdSense",
            iconPath="/static/services/google_adsense.png",
            keywords=["adsense", "ads"],
            caption=(
                "Connect a Google AdSense account to sync daily earnings and performance data "
                "(clicks, impressions, CTR, cost per click, estimated earnings). Requires a Google "
                "account with access to the AdSense account, as owner or as an invited Standard/Admin user."
            ),
            featureFlag="dwh-google-adsense",
            releaseStatus=ReleaseStatus.ALPHA,
            docsUrl="https://posthog.com/docs/cdp/sources/google-adsense",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="google_adsense_integration_id",
                        label="Google AdSense account",
                        kind="google-adsense",
                        required=True,
                        requiredScopes="https://www.googleapis.com/auth/adsense.readonly",
                    ),
                    SourceFieldOauthAccountSelectConfig(
                        name="account",
                        label="AdSense account",
                        integrationField="google_adsense_integration_id",
                        integrationKind="google-adsense",
                        placeholder="accounts/pub-1234567890123456",
                        caption=(
                            "The AdSense account to pull data from, as returned by Google "
                            "(format `accounts/pub-XXXXXXXXXXXXXXXX`). Choose from accounts your "
                            "authenticated Google user has access to, whether as owner or as an "
                            "invited Standard/Admin user."
                        ),
                        required=True,
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date",
                        required=False,
                        type=SourceFieldInputConfigType.TEXT,
                        caption="The earliest date to pull data from, in YYYY-MM-DD format. Leave blank to default to 2 years of history.",
                        placeholder="YYYY-MM-DD",
                        secret=False,
                    ),
                ],
            ),
        )
