from typing import TYPE_CHECKING, Optional, cast

from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
    SuggestedTable,
)

from posthog.exceptions_capture import capture_exception
from posthog.models.integration import OauthIntegration

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    FieldType,
    ResumableSource,
    WebhookCreationResult,
    WebhookDeletionResult,
    WebhookSource,
    WebhookSyncResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import StripeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.constants import (
    CHARGE_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    RESOURCE_TO_STRIPE_OBJECT_TYPE,
    RESOURCE_TO_STRIPE_WEBHOOK_EVENT,
    SUBSCRIPTION_RESOURCE_NAME,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.settings import (
    APPEND_ONLY_INCREMENTAL_FIELDS as STRIPE_APPEND_ONLY_INCREMENTAL_FIELDS,
    ENDPOINTS as STRIPE_ENDPOINTS,
    WEBHOOK_ONLY_ENDPOINTS as STRIPE_WEBHOOK_ONLY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe import (
    StripeAuthenticationError,
    StripePermissionError,
    StripeResumeConfig,
    StripeValidationError,
    _all_known_webhook_events,
    check_endpoint_permissions as check_stripe_endpoint_permissions,
    create_webhook,
    delete_webhook,
    get_external_webhook_info,
    stripe_source,
    update_webhook_events,
    validate_credentials as validate_stripe_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

STRIPE_BASE_URL = "https://dashboard.stripe.com"
STRIPE_ACCOUNT_URL = f"{STRIPE_BASE_URL}/settings/account"

# The API keys URL will pre-fill the form with the account ID, key name and also all the required permissions.
PERMISSIONS = [
    "rak_balance_transaction_source_read",
    "rak_charge_read",
    "rak_customer_read",
    "rak_dispute_read",
    "rak_payout_read",
    "rak_product_read",
    "rak_credit_note_read",
    "rak_invoice_read",
    "rak_plan_read",  # This is `price` in the UI, but `plan` in their API
    "rak_subscription_read",
    "rak_application_fee_read",
    "rak_transfer_read",
    "rak_connected_account_read",
    "rak_payment_method_read",
    "rak_webhook_write",
]
STRIPE_API_KEYS_URL = f"{STRIPE_BASE_URL}/apikeys/create?name=PostHog&{'&'.join([f'permissions[{i}]={permission}' for i, permission in enumerate(PERMISSIONS)])}"


@SourceRegistry.register
class StripeSource(
    ResumableSource[StripeSourceConfig, StripeResumeConfig],
    WebhookSource[StripeSourceConfig],
    OAuthMixin,
):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    has_managed_hogql_schema = True  # canonical Stripe schema in external_table_definitions

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STRIPE

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.webhook_template import template

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return RESOURCE_TO_STRIPE_OBJECT_TYPE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.STRIPE,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            caption=f"Connect your Stripe account to automatically sync your Stripe data into PostHog. You can choose between OAuth (recommended) or legacy RAK Stripe keys. If you choose the latter, you will need your [Stripe account ID]({STRIPE_ACCOUNT_URL}), and create a [restricted API key]({STRIPE_API_KEYS_URL})",
            permissionsCaption="""Currently, **read permissions are required** for the following resources:
            - Under the **Core** resource type, select *read* for **Balance transaction sources**, **Charges**, **Customers**, **Disputes**, **Payment methods**, **Payouts**, and **Products**
            - Under the **Billing** resource type, select *read* for **Credit notes**, **Invoices**, **Prices**, and **Subscriptions**
            - Under the **Connect** resource type, select *read* for the **entire resource**
            - Under the **Webhooks** resource type, select *write* for **Webhook endpoints** (required for automatic webhook creation)
            These permissions are automatically pre-filled in the API key creation form if you use the link above, so all you need to do is scroll down and click "Create Key".
            """,
            iconPath="/static/services/stripe.png",
            docsUrl="https://posthog.com/docs/cdp/sources/stripe",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="auth_method",
                        label="Authentication type",
                        required=True,
                        defaultValue="api_key",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="Restricted API key",
                                value="api_key",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="stripe_secret_key",
                                            label="API key",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=True,
                                            placeholder="rk_live_...",
                                            caption=f"Create a [restricted API key]({STRIPE_API_KEYS_URL}) with the pre-defined permissions",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="OAuth connection",
                                value="oauth",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldOauthConfig(
                                            name="stripe_integration_id",
                                            label="Stripe account",
                                            required=True,
                                            kind="stripe",
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="stripe_account_id",
                        label="Account id",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="stripe_account_id",
                        secret=False,
                    ),
                ],
            ),
            suggestedTables=[
                SuggestedTable(
                    table=CUSTOMER_RESOURCE_NAME,
                    tooltip="Enable for the best Revenue analytics experience.",
                ),
                SuggestedTable(
                    table=CHARGE_RESOURCE_NAME,
                    tooltip="Enable for the best Revenue analytics experience.",
                ),
                SuggestedTable(
                    table=INVOICE_RESOURCE_NAME,
                    tooltip="Enable for the best Revenue analytics experience.",
                ),
                SuggestedTable(
                    table=SUBSCRIPTION_RESOURCE_NAME,
                    tooltip="Enable for the best Revenue analytics experience.",
                ),
                SuggestedTable(
                    table=PRODUCT_RESOURCE_NAME,
                    tooltip="Enable for the best Revenue analytics experience.",
                ),
            ],
            featured=True,
            webhookSetupCaption="""To set up the webhook manually:

1. Go to your [Stripe Dashboard > Developers > Webhooks](https://dashboard.stripe.com/webhooks)
2. Click **Add endpoint**
3. Paste the webhook URL shown below into the **Endpoint URL** field
4. Under **Events to send**, select **All events** (or choose specific events matching your synced tables)
5. Click **Add endpoint**

Once created, copy the **Signing secret** from the webhook details page and add it to your source configuration for signature verification.

If automatic creation failed due to a permissions error and you're using a restricted API key (not OAuth), your key needs **Write** access on **Webhook endpoints**. You can update this in your [Stripe API keys settings](https://dashboard.stripe.com/apikeys).""",
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="signing_secret",
                        label="Signing secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="whsec_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.stripe.com": "Your Stripe credentials do not have permissions to access endpoint. Please check your configuration and permissions in Stripe, then try again.",
            "403 Client Error: Forbidden for url: https://api.stripe.com": "Your Stripe credentials do not have permissions to access endpoint. Please check your configuration and permissions in Stripe, then try again.",
            "Expired API Key provided": "Your Stripe API key has expired. Please create a new key and reconnect.",
            "Invalid API Key provided": None,
            # Stripe rejects the request when the restricted key has an IP allowlist that doesn't
            # include PostHog's egress IPs. This is a customer-side key configuration that retrying
            # can never satisfy, so stop retrying. Match the stable phrase, not the appended IP.
            "does not allow requests from your IP address": "Your Stripe API key restricts requests by IP address and is blocking PostHog. Remove the IP restriction on your restricted key in Stripe (or allowlist PostHog's IP addresses), then try again.",
            # Surface Stripe's raw permission message — it names the specific scope that's missing
            # (e.g. "Having the 'rak_payment_method_read' permission would allow this request to
            # continue"), which is more actionable than a generic "check your permissions" toast.
            # `_clean_stripe_error_message` collapses the redacted-key asterisk run before the
            # message reaches this layer, so it stays toast-sized.
            #
            # NOTE: this `"PermissionError"` key only matches the refresh-schemas path, which compares
            # against `f"{type(error).__name__}: {message}"`. The import/sync path compares against
            # `str(exc)` only — and `StripeError.__str__` returns `"Request <id>: <message>"` with no
            # class name — so the type-name key never matches a 403 raised mid-sync. Match Stripe's
            # stable permission-denied message text directly so a misconfigured key stops retrying.
            "PermissionError": None,
            # Restricted key is missing a read scope for the endpoint being synced (e.g. "Prices Read"
            # / 'plan_read'). The customer must add the scope in Stripe — retrying won't help. Surface
            # Stripe's raw message (None) since it names the exact scope to enable.
            "does not have the required permissions for this endpoint": None,
            # A non-Connect key was sent with a `stripe_account` header (the source's "Account id"),
            # so Stripe rejects the whole request for the account rather than a specific scope.
            "Only Stripe Connect platforms can work with other accounts": "Stripe rejected the request because your API key isn't authorized for the configured Stripe account. The 'Account id' in your source settings only applies to Stripe Connect platform accounts — remove or correct it if your key belongs directly to the account, then reconnect.",
            # Stripe's `account_invalid` rejection: the key can't reach the configured account (a
            # `stripe_account` header it isn't authorized for) or the connected application's access
            # was revoked. Surfaced mid-sync as `stripe.PermissionError` straight out of `get_rows`,
            # so it never matches the URL-based 403 key. Retrying can't fix a key/account mismatch or
            # a revoked grant — match Stripe's stable message (the account id and key are redacted out
            # of the substring). `_is_stripe_account_access_error` classifies the same phrase for the
            # webhook-creation path.
            "does not have access to account": "Stripe rejected the request because your API key isn't authorized for the configured Stripe account. Remove or correct the 'Account id' in your source settings if your key belongs directly to the account. If you connected via OAuth, the application access may have been revoked — reconnect your Stripe account.",
            # Deterministic credential/config errors from _get_api_key and OAuthMixin
            "Missing Stripe API key": "Stripe API key is not configured. Please update the source configuration.",
            "Missing Stripe integration ID": "Stripe integration ID is not configured. Please reconnect your Stripe account.",
            "Missing integration ID": "Integration ID is not configured. Please reconnect your Stripe account.",
            "Integration not found": "The linked Stripe integration no longer exists. Please reconnect your Stripe account.",
            "Stripe access token not found": "Stripe OAuth access token is missing. Please reconnect your Stripe account.",
            "Your Stripe OAuth connection has expired or been revoked. Please reconnect your Stripe account.": "Your Stripe OAuth connection has expired or been revoked. Please reconnect your Stripe account.",
        }

    def _get_api_key(self, config: StripeSourceConfig, team_id: int) -> str:
        if config.auth_method.selection == "api_key":
            if not config.auth_method.stripe_secret_key:
                raise ValueError("Missing Stripe API key")
            return config.auth_method.stripe_secret_key

        if not config.auth_method.stripe_integration_id:
            raise ValueError("Missing Stripe integration ID")

        integration = self.get_oauth_integration(config.auth_method.stripe_integration_id, team_id)

        oauth_integration = OauthIntegration(integration)
        if oauth_integration.access_token_expired():
            oauth_integration.refresh_access_token()

        if not integration.access_token:
            raise ValueError("Stripe access token not found")
        return integration.access_token

    def get_schemas(
        self,
        config: StripeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                # An endpoint supports webhooks iff a Stripe event emits its object type — i.e. it's in
                # RESOURCE_TO_STRIPE_WEBHOOK_EVENT (the same map that drives event subscription) — or
                # it's webhook-only (e.g. Discount, no list API). This is what lets CustomerPaymentMethod
                # move to webhook sync after its initial backfill instead of re-sweeping every customer,
                # while CustomerBalanceTransaction (no Stripe event) stays API-sweep-only.
                supports_webhooks=(
                    endpoint in RESOURCE_TO_STRIPE_WEBHOOK_EVENT or endpoint in STRIPE_WEBHOOK_ONLY_ENDPOINTS
                ),
                webhook_only=endpoint in STRIPE_WEBHOOK_ONLY_ENDPOINTS,
                # nested resources are only full refresh and are not in STRIPE_APPEND_ONLY_INCREMENTAL_FIELDS
                supports_append=STRIPE_APPEND_ONLY_INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=STRIPE_APPEND_ONLY_INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in STRIPE_ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: StripeSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
    ) -> tuple[bool, str | None]:
        # No schema_name → basic auth probe. With schema_name → probe that endpoint.
        endpoints = [schema_name] if schema_name is not None else None
        try:
            api_key = self._get_api_key(config, team_id)
            if validate_stripe_credentials(api_key, endpoints, auth_method=config.auth_method.selection):
                return True, None
            else:
                return False, "Invalid Stripe credentials"
        except StripeAuthenticationError:
            if config.auth_method.selection == "oauth":
                return (
                    False,
                    "Your Stripe OAuth connection has expired or been revoked. Please reconnect your Stripe account.",
                )
            # Stripe's 401 body echoes the rejected key verbatim, so interpolating `e.stripe_message`
            # leaks whatever the user pasted (often a password) into the toast and the
            # `warehouse credentials invalid` analytics event. The guidance below stands on its own.
            return (
                False,
                "Stripe rejected the API key. Double-check that you pasted a restricted key (rk_live_...) for the same Stripe account, with no extra whitespace, and that it has not been revoked.",
            )
        except StripePermissionError as e:
            # 403s are self-explanatory — the resource name tells the customer which Stripe scope
            # to enable. Stripe's verbose error (request id, status, headers) bloats the toast
            # without adding signal, so render a plain resource list.
            return (
                False,
                f"Stripe credentials lack permissions for {', '.join(e.missing_permissions.keys())}",
            )
        except StripeValidationError as e:
            # Non-403 failures (network, schema, rate limit, etc.) are not configuration issues, so
            # surface the underlying Stripe message verbatim — the cause isn't obvious from the
            # resource name. Fold any 403s collected before the unknown error into the same toast.
            # Guard against empty / whitespace-only error strings so we never crash the response
            # path while reporting a different error.
            def _first_line(msg: str) -> str:
                lines = (msg or "").splitlines()
                return lines[0][:200] if lines else "(no detail)"

            details = "; ".join(f"{name}: {_first_line(msg)}" for name, msg in e.errors.items())
            message = f"Stripe validation failed — {details}"
            if e.missing_permissions:
                message += f". Additionally lacks permissions for {', '.join(e.missing_permissions.keys())}"
            return False, message
        except ValueError as e:
            # `_get_api_key` raises ValueError for deterministic config problems (missing API key,
            # missing integration ID, missing access token). The user-facing wording already lives
            # in `get_non_retryable_errors`; reuse it so this path doesn't leak the internal
            # "Missing Stripe integration ID" string. Fall back to the raw message if unmapped.
            raw = str(e)
            for pattern, friendly in self.get_non_retryable_errors().items():
                if friendly and pattern in raw:
                    return False, friendly
            return False, raw
        except Exception as e:
            return False, str(e)

    def get_endpoint_permissions(
        self, config: StripeSourceConfig, team_id: int, endpoints: list[str]
    ) -> dict[str, str | None]:
        # 401 → mark every endpoint with the auth error so caller can surface it once.
        try:
            api_key = self._get_api_key(config, team_id)
        except ValueError as e:
            # Known credential-config issues from _get_api_key — message is curated and safe to surface.
            return dict.fromkeys(endpoints, str(e))
        except Exception as e:
            # Unknown failure (OAuth refresh, integration lookup, etc.). Capture for triage but
            # render a generic reason so we never leak an unintended message to the UI.
            capture_exception(e)
            return dict.fromkeys(endpoints, "Stripe credentials are not available")

        try:
            return check_stripe_endpoint_permissions(api_key, endpoints, auth_method=config.auth_method.selection)
        except StripeAuthenticationError as e:
            return dict.fromkeys(endpoints, e.stripe_message)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[StripeResumeConfig]:
        return ResumableSourceManager[StripeResumeConfig](inputs, StripeResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(self, config: StripeSourceConfig, webhook_url: str, team_id: int) -> WebhookCreationResult:
        api_key = self._get_api_key(config, team_id)
        return create_webhook(api_key, config.stripe_account_id, webhook_url)

    def get_desired_webhook_events(
        self, config: StripeSourceConfig, eligible_schema_names: list[str]
    ) -> list[str] | None:
        # Every mappable event, not just the selected tables — auto-heals webhooks created
        # before RESOURCE_TO_STRIPE_WEBHOOK_EVENT gained new resources.
        return _all_known_webhook_events()

    def sync_webhook_events(
        self,
        config: StripeSourceConfig,
        webhook_url: str,
        team_id: int,
        eligible_schema_names: list[str],
    ) -> WebhookSyncResult:
        api_key = self._get_api_key(config, team_id)
        desired_events = self.get_desired_webhook_events(config, eligible_schema_names) or []
        return update_webhook_events(api_key, config.stripe_account_id, webhook_url, desired_events)

    def get_external_webhook_info(
        self, config: StripeSourceConfig, webhook_url: str, team_id: int
    ) -> ExternalWebhookInfo:
        api_key = self._get_api_key(config, team_id)
        return get_external_webhook_info(api_key, config.stripe_account_id, webhook_url)

    def delete_webhook(self, config: StripeSourceConfig, webhook_url: str, team_id: int) -> WebhookDeletionResult:
        api_key = self._get_api_key(config, team_id)
        return delete_webhook(api_key, config.stripe_account_id, webhook_url)

    def source_for_pipeline(
        self,
        config: StripeSourceConfig,
        resumable_source_manager: ResumableSourceManager[StripeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        webhook_source_manager = self.get_webhook_source_manager(inputs)
        api_key = self._get_api_key(config, inputs.team_id)

        return stripe_source(
            api_key=api_key,
            account_id=config.stripe_account_id,
            endpoint=inputs.schema_name,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            db_incremental_field_earliest_value=inputs.db_incremental_field_earliest_value,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            webhook_source_manager=webhook_source_manager,
        )
