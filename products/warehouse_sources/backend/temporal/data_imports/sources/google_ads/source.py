import re
import datetime
from typing import Optional, cast

from django.core.cache import cache

import requests
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthAccountSelectConfig,
    SourceFieldOauthConfig,
    SourceFieldSwitchGroupConfig,
    SuggestedTable,
)

from posthog.models.integration import (
    ERROR_TOKEN_REFRESH_FAILED,
    GoogleAdsIntegration,
    Integration,
    OauthIntegration,
    google_ads_hierarchy_level,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP,
    FieldType,
    ResumableSource,
    VersionDeprecation,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccount,
    IntegrationAccountListingError,
    filter_integration_accounts,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googleads import (
    GoogleAdsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.configs import (
    GOOGLE_ADS_INITIAL_BACKFILL_DAYS,
    GoogleAdsResumeConfig,
    GoogleAdsServiceAccountSourceConfig,
    clean_customer_id,
    format_customer_id,
    parse_start_date,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Default incremental overlap re-read window for Google Ads stats tables (those carrying a
# `segments.date` filter). Google reports recent-day cost/conversion data as provisional and keeps
# revising it for days after the fact (see "About data freshness":
# https://support.google.com/google-ads/answer/2544985), so an incremental sync that only re-fetches
# the newest day freezes each day at its first-imported, not-yet-final value. Re-reading a trailing
# window each run lets those days catch up; merge-by-primary-key makes the overlap idempotent.
#
# The window is a direct multiplier on the rows an incremental run reports: on the largest stats
# tables (`search_term_stats`, `keyword_stats`, which grow with query volume rather than account
# size) an N-day window costs roughly N times the rows of a newest-day-only sync. Two weeks buys
# most of Google's restatement window at half that cost. Only schemas created from here on pick this
# up — existing schemas keep whatever lookback they already carry. It sits above the length at which
# SyncMethodForm warns a window is expensive, so accounts that would rather sync less lower it per
# schema, up to the 60-day cap the creation/update endpoints enforce.
GOOGLE_ADS_STATS_INCREMENTAL_LOOKBACK_SECONDS = 15 * 24 * 60 * 60

_OAUTH_ACCOUNTS_CACHE_TTL_SECONDS = 60


def _oauth_accounts_cache_key(team_id: int, integration_id: int) -> str:
    # Keyed on (team, integration) only — never the search term — so distinct searches share one walk.
    return f"@dwh/google_ads/{team_id}/{integration_id}/oauth_accounts"


@SourceRegistry.register
class GoogleAdsSource(
    ResumableSource[GoogleAdsSourceConfig | GoogleAdsServiceAccountSourceConfig, GoogleAdsResumeConfig], OAuthMixin
):
    supported_versions = ("v23", "v24", "v25")
    default_version = "v25"
    api_docs_url = "https://developers.google.com/google-ads/api/docs/release-notes"
    # Google sunsets each major ~12 months after release. v23 (released 2026-01-28) is scheduled to
    # sunset in February 2027; Google has announced the month but not the exact day, so pin the
    # conservative first-of-month — the deprecation banner and the v23→v25 repin migration key off it.
    # v24 (released 2026-04-22) is projected for ~May 2027 with no firm date on the sunset page yet,
    # so its `sunset_at` stays None until Google publishes one and existing v24 pins stay on v24.
    deprecated_versions = (
        VersionDeprecation(version="v23", sunset_at=datetime.date(2027, 2, 1)),
        VersionDeprecation(version="v24", sunset_at=None),
    )

    history_lookback = datetime.timedelta(days=GOOGLE_ADS_INITIAL_BACKFILL_DAYS)

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEADS

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Order matters: the finalization activity shows the message of the *first* pattern that
        # matches, and Google returns several of the specific codes below under the generic
        # `PERMISSION_DENIED` / `UNAUTHENTICATED` gRPC statuses. Specific codes therefore come first,
        # so a scope or deleted-account failure doesn't get the generic access message.
        return {
            "ACCESS_TOKEN_SCOPE_INSUFFICIENT": "Your Google Ads connection is missing the access PostHog needs. Reconnect your Google Ads account and allow access to your Google Ads data.",
            "Account has been deleted": "The Google Ads account this source syncs from has been deleted, so there's nothing left to import. Point the source at an active customer ID, or delete the source.",
            "INVALID_CUSTOMER_ID": "The customer ID on this source isn't a valid Google Ads account. Update it to the 10-digit customer ID shown in your Google Ads account, then re-enable the sync.",
            "REQUESTED_METRICS_FOR_MANAGER": "Metrics cannot be requested for a Google Ads manager (MCC) account. Reconfigure this source with a client account customer ID, or enable the MCC option and provide both the manager and client customer IDs.",
            # A gRPC PERMISSION_DENIED (and its ads-level USER_PERMISSION_DENIED counterpart) means the
            # connected Google login can't reach this customer ID. The sync already retries as the
            # manager account that can reach it (see `GoogleAdsSearchService`), so anything landing here
            # is access the login genuinely doesn't have. Its str() is a raw gRPC status and protobuf
            # dump (with a per-request peer IP) the user can't act on, so replace it.
            "PERMISSION_DENIED": (
                "The connected Google login can't access this Google Ads account. Check the customer ID "
                "is correct and still shared with that login, and if it's a client account under a "
                'manager (MCC) account, enable "Using MCC account?" and enter your manager\'s customer '
                "ID. Then reconnect your Google Ads account and re-enable the sync."
            ),
            # A gRPC UNAUTHENTICATED means Google rejected the credentials outright. Same story: the raw
            # status dump is unusable and only reconnecting recovers.
            "UNAUTHENTICATED": "Your Google Ads connection could not be authenticated. Please reconnect your Google Ads account.",
            # google.auth.exceptions.RefreshError raised when the stored OAuth refresh token
            # has been revoked, expired, or is otherwise rejected by Google's token endpoint.
            # Retrying cannot recover — the user must reconnect their Google Ads account.
            "invalid_grant": "Your Google Ads connection has expired or been revoked. Please reconnect your Google Ads account.",
            # google.auth.exceptions.RefreshError raised when the user's Google Workspace admin
            # has restricted third-party API access for this app (org policy / app not approved).
            # Retrying cannot recover — an admin must grant access before the user reconnects.
            "access_not_configured": "Your Google Workspace administrator has restricted API access for this app. Ask your admin to approve it, then reconnect your Google Ads account.",
            # Integration.DoesNotExist raised by `google_ads_client` when the stored OAuth
            # integration row has been deleted/disconnected before the sync runs. Retrying cannot
            # recover — the user must reconnect their Google Ads account. Model-specific so we don't
            # swallow unrelated `DoesNotExist` errors from other models, which may be real bugs.
            "Integration matching query does not exist": "Your Google Ads connection is no longer available — it may have been disconnected. Please reconnect your Google Ads account.",
            # gapic wraps a transport-level UNAUTHENTICATED into google.api_core.exceptions.Unauthenticated,
            # whose str() is "401 Request is missing required authentication credential. ..." — it never
            # contains the bare "UNAUTHENTICATED" token, so the gRPC-status keys above don't catch it.
            # Retrying cannot recover — the user must reconnect their Google Ads account.
            "Request is missing required authentication credential": "Your Google Ads connection could not be authenticated. Please reconnect your Google Ads account.",
            # The other gapic-wrapped Unauthenticated variant, str() "401 Request had invalid authentication
            # credentials. ..." — raised when the OAuth access token itself is rejected. Same story: no bare
            # "UNAUTHENTICATED" token, retrying cannot recover, the user must reconnect their Google Ads account.
            "Request had invalid authentication credentials": "Your Google Ads connection could not be authenticated. Please reconnect your Google Ads account.",
        }

    def get_retryable_errors(self) -> set[str]:
        # A quota/rate-limit RESOURCE_EXHAUSTED ("Resource has been exhausted (e.g. check
        # quota).") is already ridden out in-process by `_call_with_transient_retry` (see
        # `_is_transient_grpc_error` in google_ads.py). A search that still fails after that
        # budget has hit a longer-lived quota window than a few seconds of backoff can clear,
        # but Temporal's activity retry recovers once it does — self-recovering, not a bug, so
        # keep it out of error tracking as noise.
        return {"Resource has been exhausted (e.g. check quota)"}

    # TODO: clean up google ads source to not have two auth config options
    def parse_config(self, job_inputs: dict) -> GoogleAdsSourceConfig | GoogleAdsServiceAccountSourceConfig:
        if "google_ads_integration_id" in job_inputs.keys():
            return self._config_class.from_dict(job_inputs)

        return GoogleAdsServiceAccountSourceConfig.from_dict(job_inputs)

    def get_schemas(
        self,
        config: GoogleAdsSourceConfig | GoogleAdsServiceAccountSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Deferred so registering this source doesn't import the google-ads SDK — see configs.py.
        from products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.google_ads import (  # noqa: PLC0415
            get_incremental_fields as get_google_ads_incremental_fields,
            get_schemas as get_google_ads_schemas,
        )

        # Discover against the source's pinned version (falling back to the default) so a
        # v23-pinned source reconciles schemas under v23, matching its sync path — not v24.
        google_ads_schemas = get_google_ads_schemas(
            config,
            team_id,
            self.resolve_api_version(api_version),
        )

        ads_incremental_fields = get_google_ads_incremental_fields()

        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=ads_incremental_fields.get(endpoint, None) is not None,
                supports_append=ads_incremental_fields.get(endpoint, None) is not None,
                incremental_fields=[
                    {"label": column_name, "type": column_type, "field": column_name, "field_type": column_type}
                    for column_name, column_type in ads_incremental_fields.get(endpoint, [])
                ],
                description=endpoint_config.description,
                should_sync_default=endpoint_config.should_sync_default,
                # Only the incremental stats tables (those with a segments.date filter) need the
                # lookback; the full-refresh dimension tables re-read everything each run anyway.
                default_incremental_lookback_seconds=(
                    GOOGLE_ADS_STATS_INCREMENTAL_LOOKBACK_SECONDS
                    if ads_incremental_fields.get(endpoint, None) is not None
                    else None
                ),
            )
            for endpoint, endpoint_config in google_ads_schemas.items()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GoogleAdsResumeConfig]:
        return ResumableSourceManager[GoogleAdsResumeConfig](inputs, GoogleAdsResumeConfig)

    def source_for_pipeline(
        self,
        config: GoogleAdsSourceConfig | GoogleAdsServiceAccountSourceConfig,
        resumable_source_manager: ResumableSourceManager[GoogleAdsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        from products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.google_ads import (
            google_ads_source,  # noqa: PLC0415
        )

        return google_ads_source(
            config=config,
            resource_name=inputs.schema_name,
            team_id=inputs.team_id,
            resumable_source_manager=resumable_source_manager,
            api_version=self.resolve_api_version(inputs.api_version),
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field if inputs.should_use_incremental_field else None,
            incremental_field_type=inputs.incremental_field_type if inputs.should_use_incremental_field else None,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            db_incremental_field_last_value_before_lookback=inputs.db_incremental_field_last_value_before_lookback,
            history_start=inputs.history_start,
            requested_start=config.start_date if isinstance(config, GoogleAdsSourceConfig) else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GOOGLE_ADS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            featured=True,
            keywords=["adwords"],
            label="Google Ads",
            caption="Ensure you have granted PostHog access to your Google Ads account, learn how to do this in [the docs](https://posthog.com/docs/cdp/sources/google-ads).",
            releaseStatus=ReleaseStatus.GA,
            iconPath="/static/services/google-ads.png",
            docsUrl="https://posthog.com/docs/cdp/sources/google-ads",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="google_ads_integration_id",
                        label="Google Ads account",
                        required=True,
                        kind="google-ads",
                        requiredScopes="https://www.googleapis.com/auth/adwords",
                    ),
                    SourceFieldOauthAccountSelectConfig(
                        name="customer_id",
                        label="Customer ID",
                        integrationField="google_ads_integration_id",
                        integrationKind="google-ads",
                        required=True,
                        placeholder="123-456-7890",
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date",
                        caption=(
                            "Earliest date to import, as YYYY-MM-DD. On a source that has already "
                            "synced, changing this takes effect on the next full re-import — Sync "
                            "keeps going from where it left off. Leave empty for the last two years; "
                            "an earlier date imports more rows, which count towards your billed row usage."
                        ),
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="2020-01-01",
                        secret=False,
                    ),
                    SourceFieldSwitchGroupConfig(
                        name="is_mcc_account",
                        label="Using MCC account?",
                        caption="Whether your account is a Google Ads MCC account and you're accessing a clients account?",
                        default=False,
                        fields=cast(
                            list[FieldType],
                            [
                                SourceFieldInputConfig(
                                    name="mcc_client_id",
                                    label="Managers customer ID",
                                    type=SourceFieldInputConfigType.TEXT,
                                    required=True,
                                    placeholder="123-456-7890",
                                    secret=False,
                                )
                            ],
                        ),
                    ),
                ],
            ),
            suggestedTables=[
                SuggestedTable(
                    table="campaign",
                    tooltip=MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP,
                ),
                SuggestedTable(
                    table="campaign_overview_stats",
                    tooltip=MARKETING_ANALYTICS_SUGGESTED_TABLE_TOOLTIP,
                ),
            ],
        )

    def get_oauth_accounts(
        self, integration_id: int, team_id: int, search: str | None = None
    ) -> list[IntegrationAccount]:
        # The whole account list comes from one expensive hierarchy walk (listAccessibleCustomers plus a
        # searchStream per accessible root) that ignores `search`. Cache the unfiltered result keyed only
        # on (team, integration) — never `search` — so distinct search terms reuse one walk instead of
        # repeating it and burning shared Google Ads API quota, then filter the cached list in memory.
        cache_key = _oauth_accounts_cache_key(team_id, integration_id)
        cached = cache.get(cache_key)
        if cached is not None:
            return filter_integration_accounts(cached, search)

        try:
            integration = self.get_oauth_integration(integration_id, team_id)
        except ValueError as e:
            raise IntegrationAccountListingError(
                "The linked Google Ads integration could not be found. Please reconnect your Google Ads integration."
            ) from e

        oauth = OauthIntegration(integration)
        if integration.errors != ERROR_TOKEN_REFRESH_FAILED and oauth.access_token_expired():
            oauth.refresh_access_token()
        if integration.errors == ERROR_TOKEN_REFRESH_FAILED:
            raise IntegrationAccountListingError(
                "Could not refresh the Google Ads credentials. Please reconnect your Google Ads integration."
            )

        try:
            accounts = GoogleAdsIntegration(integration).list_google_ads_accessible_accounts()
        except ValidationError as e:
            # Raised only for a 401/403 from Google: revoked credentials, or the connected account
            # lost access.
            raise IntegrationAccountListingError(
                "Google rejected the credentials for this integration. Please reconnect your Google Ads "
                "integration and make sure the connected account can access your Google Ads accounts."
            ) from e
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            # The walk retries a transient blip internally; this means every attempt on some request
            # timed out or failed to connect. Actionable and retryable from the user's side, so surface
            # a clean message instead of the raw connection error.
            raise IntegrationAccountListingError(
                "Google Ads did not respond in time while listing your accounts. Please try again."
            ) from e

        names_by_id = {account["id"]: account["name"] for account in accounts}
        integration_accounts = [
            IntegrationAccount(
                # Dashed as the Google Ads UI shows it; clean_customer_id normalizes to bare at the API boundary.
                value=format_customer_id(account["id"]),
                display_name=account["name"],
                is_primary=google_ads_hierarchy_level(account) == 0,
                badges=("Manager",) if account.get("manager") else (),
                # `parent_id` is the accessible account the walk started from, not the direct manager, so
                # it only names the true parent one level down. Deeper accounts get no group rather than a
                # wrong one (the client renders this as "under <group>").
                group=names_by_id.get(account["parent_id"]) if google_ads_hierarchy_level(account) == 1 else None,
            )
            for account in accounts
        ]

        # Don't cache an empty result: a transient walk that returns [] without raising would otherwise
        # freeze the picker empty for the whole TTL for every admin on the team.
        if integration_accounts:
            cache.set(cache_key, integration_accounts, _OAUTH_ACCOUNTS_CACHE_TTL_SECONDS)
        return filter_integration_accounts(integration_accounts, search)

    def validate_config(self, job_inputs: dict) -> tuple[bool, list[str]]:
        is_valid, errors = super().validate_config(job_inputs)

        # Normalize before validating: `clean_customer_id` strips dashes, spaces and
        # whitespace, so `123-456-7890`, `1234567890`, or a copy-pasted value all pass.
        # The same normalization is applied wherever the id is sent to the API. We guard
        # on the raw value so a non-numeric entry (which normalizes to empty) is still
        # rejected rather than silently slipping through.
        raw_customer_id = job_inputs.get("customer_id", "")
        if raw_customer_id and not re.fullmatch(r"\d{10}", clean_customer_id(raw_customer_id) or ""):
            errors.append(
                "Please enter a valid Google Ads customer ID — the 10-digit number from your "
                "Google Ads account (dashes optional)."
            )
            is_valid = False

        # The switch-group field is a dict (`{"enabled": ..., "mcc_client_id": ...}`) when
        # sent from the setup form, but API callers may send a plain bool, so only treat it
        # as enabled when it's the expected dict shape.
        is_mcc_account = job_inputs.get("is_mcc_account")
        if isinstance(is_mcc_account, dict) and is_mcc_account.get("enabled"):
            raw_mcc_client_id = is_mcc_account.get("mcc_client_id", "")
            if raw_mcc_client_id and not re.fullmatch(r"\d{10}", clean_customer_id(raw_mcc_client_id) or ""):
                errors.append(
                    "Please enter a valid Google Ads manager customer ID — the 10-digit number from "
                    "your manager account (dashes optional)."
                )
                is_valid = False

        return is_valid, errors

    def _validate_mcc_customer_access(
        self, client, config: GoogleAdsSourceConfig, api_version: str
    ) -> tuple[bool, str | None]:
        """Validate that a client account is accessible through a manager (MCC) account.

        list_accessible_customers() only returns manager-level accounts, not client accounts
        under those managers. We directly query the target customer - if the MCC login_customer_id
        is configured correctly in the client, this will succeed.
        """
        cleaned_customer_id = clean_customer_id(config.customer_id)
        ga_service = client.get_service("GoogleAdsService", version=api_version)
        query = "SELECT customer.id FROM customer"
        try:
            response = ga_service.search(customer_id=cleaned_customer_id, query=query)
            list(response)  # Consume the response to trigger any errors
            return True, None
        except Exception as e:
            error_message = str(e)
            if "CUSTOMER_NOT_FOUND" in error_message or "USER_PERMISSION_DENIED" in error_message:
                return (
                    False,
                    f"Customer ID {config.customer_id} isn't accessible through the connected manager "
                    "(MCC) account. Check that the customer ID is correct, that the manager customer ID "
                    "you entered is right, and that this account is linked under that manager, then try again.",
                )
            raise

    def validate_credentials(
        self,
        config: GoogleAdsSourceConfig | GoogleAdsServiceAccountSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.google_ads import (  # noqa: PLC0415
            _is_transient_grpc_error,
            google_ads_client,
        )

        # Caught here rather than at sync time: an unreadable value is treated as unset there, so
        # the source would import a range nobody asked for with nothing to say why.
        if isinstance(config, GoogleAdsSourceConfig) and config.start_date:
            try:
                parse_start_date(config.start_date)
            except ValueError:
                return False, "Start date must be a date in YYYY-MM-DD format, for example 2020-01-01."

        # The SDK's client default is the newest bundled version, so leaving these probes unpinned
        # would validate against a version the source may not sync with.
        resolved_version = self.resolve_api_version(api_version)

        try:
            client = google_ads_client(config, team_id)

            if isinstance(config, GoogleAdsSourceConfig) and config.is_mcc_account and config.is_mcc_account.enabled:
                return self._validate_mcc_customer_access(client, config, resolved_version)

            customer_service = client.get_service("CustomerService", version=resolved_version)
            accessible_customers = customer_service.list_accessible_customers()

            customer_resource_name = f"customers/{clean_customer_id(config.customer_id)}"
            is_valid = customer_resource_name in accessible_customers.resource_names
            if not is_valid:
                # `list_accessible_customers` returns only accounts the login can reach directly,
                # never client accounts nested under a manager. A valid client-account id therefore
                # lands here when the MCC toggle is off, so point at that toggle rather than telling
                # the user their (correct) id is wrong. Mirrors the PERMISSION_DENIED message below.
                return (
                    False,
                    f"Customer ID {config.customer_id} isn't accessible with the connected Google login. "
                    "Check the ID is correct, and if it's a client account under a manager (MCC) account, "
                    'enable "Using MCC account?" and enter your manager\'s customer ID, then try again.',
                )
            return True, None
        except Integration.DoesNotExist:
            return (
                False,
                "The Google Ads connection for this source no longer exists. Please reconnect your Google Ads account.",
            )
        except Exception as e:
            error_message = str(e)
            if "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in error_message:
                return (
                    False,
                    "Insufficient permissions. Please reconnect your Google Ads account with the required scopes.",
                )
            if "NOT_ADS_USER" in error_message:
                return (
                    False,
                    "The Google account is not associated with any Google Ads accounts. Please use an account with Google Ads access.",
                )
            if "matching query does not exist" in error_message:
                return (
                    False,
                    "Your Google Ads connection is no longer available — it may have been disconnected. "
                    "Please reconnect your Google Ads account.",
                )
            # A gRPC PERMISSION_DENIED ("The caller does not have permission") means the connected Google
            # login can't access this customer ID — the wrong customer/manager (MCC) account, or access
            # that was never granted. list_accessible_customers raises it as a raw _InactiveRpcError whose
            # str() is a protobuf dump (with a per-request peer IP) the user can't act on, so surface an
            # actionable prompt instead of leaking it, mirroring the MCC USER_PERMISSION_DENIED message.
            if "PERMISSION_DENIED" in error_message or "caller does not have permission" in error_message:
                return (
                    False,
                    "PostHog doesn't have permission to access this Google Ads account. Verify the "
                    "customer ID (and manager account, if using an MCC) is accessible to the connected "
                    "Google login, then reconnect your Google Ads account.",
                )
            # A transient Google-side blip (INTERNAL / UNAVAILABLE) stringifies as a raw gRPC status and
            # protobuf failure dump the user can't act on. The sync rides these out in-process; here on
            # the interactive create path we surface a clean retry prompt instead of leaking the dump.
            if _is_transient_grpc_error(e):
                return (
                    False,
                    "Google Ads returned a temporary error while validating your credentials. This is "
                    "usually a transient issue on Google's side — please try again in a moment.",
                )
            # A gRPC INVALID_ARGUMENT ("Request contains an invalid argument") means Google rejected the
            # request as malformed — most often a customer ID (or MCC manager ID) that isn't a valid
            # account. Its str() is the same raw protobuf dump (with a per-request peer IP) the user
            # can't act on, so surface an actionable prompt instead of leaking it.
            if "INVALID_ARGUMENT" in error_message:
                return (
                    False,
                    "Google Ads rejected the request as invalid while validating your credentials. Check "
                    "that your customer ID (and your manager account ID, if using an MCC) is correct, then "
                    "try again.",
                )
            return False, f"Error validating credentials: {error_message}"
