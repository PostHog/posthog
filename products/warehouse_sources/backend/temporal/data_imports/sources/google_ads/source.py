import re
from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
    SourceFieldSwitchGroupConfig,
    SuggestedTable,
)

from posthog.models.integration import Integration

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GoogleAdsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.configs import (
    GoogleAdsResumeConfig,
    GoogleAdsServiceAccountSourceConfig,
    clean_customer_id,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Default incremental overlap re-read window for Google Ads stats tables (the 12 schemas
# carrying a `segments.date` filter). Google reports recent-day cost/conversion data as
# provisional and keeps revising it for days after the fact (see "About data freshness":
# https://support.google.com/google-ads/answer/2544985), so an incremental sync that only
# re-fetches the newest day freezes each day at its first-imported, not-yet-final value.
# Re-reading a 30-day trailing window each run lets those days catch up as Google finalizes
# them; merge-by-primary-key makes the overlap idempotent. 30 days also covers the App-
# campaign conversion attribution window for the conversion metrics in these tables. These
# tables are small, so the extra re-read is negligible. Tunable; stays under the 60-day cap
# enforced at the creation/update endpoints.
GOOGLE_ADS_STATS_INCREMENTAL_LOOKBACK_SECONDS = 30 * 24 * 60 * 60


@SourceRegistry.register
class GoogleAdsSource(
    ResumableSource[GoogleAdsSourceConfig | GoogleAdsServiceAccountSourceConfig, GoogleAdsResumeConfig], OAuthMixin
):
    supported_versions = ("v23",)
    default_version = "v23"
    api_docs_url = "https://developers.google.com/google-ads/api/docs/release-notes"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEADS

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "PERMISSION_DENIED": None,
            "UNAUTHENTICATED": None,
            "ACCESS_TOKEN_SCOPE_INSUFFICIENT": None,
            "Account has been deleted": None,
            "INVALID_CUSTOMER_ID": None,
            "REQUESTED_METRICS_FOR_MANAGER": "Metrics cannot be requested for a Google Ads manager (MCC) account. Reconfigure this source with a client account customer ID, or enable the MCC option and provide both the manager and client customer IDs.",
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
        }

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
    ) -> list[SourceSchema]:
        # Deferred so registering this source doesn't import the google-ads SDK — see configs.py.
        from products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.google_ads import (  # noqa: PLC0415
            get_incremental_fields as get_google_ads_incremental_fields,
            get_schemas as get_google_ads_schemas,
        )

        google_ads_schemas = get_google_ads_schemas(
            config,
            team_id,
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
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field if inputs.should_use_incremental_field else None,
            incremental_field_type=inputs.incremental_field_type if inputs.should_use_incremental_field else None,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
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
                    SourceFieldInputConfig(
                        name="customer_id",
                        label="Customer ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="123-456-7890",
                        secret=False,
                    ),
                    SourceFieldOauthConfig(
                        name="google_ads_integration_id",
                        label="Google Ads account",
                        required=True,
                        kind="google-ads",
                        requiredScopes="https://www.googleapis.com/auth/adwords",
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

    def _validate_mcc_customer_access(self, client, config: GoogleAdsSourceConfig) -> tuple[bool, str | None]:
        """Validate that a client account is accessible through a manager (MCC) account.

        list_accessible_customers() only returns manager-level accounts, not client accounts
        under those managers. We directly query the target customer - if the MCC login_customer_id
        is configured correctly in the client, this will succeed.
        """
        cleaned_customer_id = clean_customer_id(config.customer_id)
        ga_service = client.get_service("GoogleAdsService")
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
                    f"Customer ID {config.customer_id} is not accessible. Please verify your customer ID and manager account settings.",
                )
            raise

    def validate_credentials(
        self,
        config: GoogleAdsSourceConfig | GoogleAdsServiceAccountSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
    ) -> tuple[bool, str | None]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.google_ads.google_ads import (  # noqa: PLC0415
            _is_transient_grpc_error,
            google_ads_client,
        )

        try:
            client = google_ads_client(config, team_id)

            if isinstance(config, GoogleAdsSourceConfig) and config.is_mcc_account and config.is_mcc_account.enabled:
                return self._validate_mcc_customer_access(client, config)

            customer_service = client.get_service("CustomerService")
            accessible_customers = customer_service.list_accessible_customers()

            customer_resource_name = f"customers/{clean_customer_id(config.customer_id)}"
            is_valid = customer_resource_name in accessible_customers.resource_names
            if not is_valid:
                return (
                    False,
                    f"Customer ID {config.customer_id} is not correct. Please check your customer ID and try again.",
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
            # A transient Google-side blip (INTERNAL / UNAVAILABLE) stringifies as a raw gRPC status and
            # protobuf failure dump the user can't act on. The sync rides these out in-process; here on
            # the interactive create path we surface a clean retry prompt instead of leaking the dump.
            if _is_transient_grpc_error(e):
                return (
                    False,
                    "Google Ads returned a temporary error while validating your credentials. This is "
                    "usually a transient issue on Google's side — please try again in a moment.",
                )
            return False, f"Error validating credentials: {error_message}"
