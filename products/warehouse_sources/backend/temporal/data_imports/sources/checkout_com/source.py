from typing import Optional, cast

import requests
import structlog

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.checkout_com import (
    ENDPOINTS,
    CheckoutComResumeConfig,
    checkout_com_source,
    validate_credentials as validate_checkout_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.payments import (
    PAYMENTS_ENDPOINTS,
    SYNC_BUDGET_EXCEEDED_MARKER,
    UNRESOLVED_REFERENCES_MARKER,
    checkout_com_payments_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.reports import (
    REPORTS_METADATA_ENDPOINT,
    checkout_com_reports_source,
    discover_report_types,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAUTH2_PERMANENT_ERROR_MARKER,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
    incremental_field,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.checkoutcom import (
    CheckoutComSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalField, IncrementalFieldType

logger = structlog.get_logger(__name__)

_DISPUTES_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "last_update",
        "type": IncrementalFieldType.DateTime,
        "field": "last_update",
        "field_type": IncrementalFieldType.DateTime,
    },
]

# The reports listing filters server-side on `created_after`.
_REPORTS_INCREMENTAL_FIELDS: list[IncrementalField] = [incremental_field("created_on")]
_REPORT_ROWS_INCREMENTAL_FIELDS: list[IncrementalField] = [incremental_field("report_created_on")]

# Payments search filters server-side on `from`/`to` over the payment request time;
# the fan-out tables inherit that cursor through the payment that references them.
_PAYMENTS_INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "payments": [incremental_field("requested_on")],
    "payment_actions": [incremental_field("payment_requested_on")],
    "customers": [incremental_field("payment_requested_on")],
    "instruments": [incremental_field("payment_requested_on")],
}

_PAYMENTS_ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    "payments": "Payment requests (approved and declined) from the payments search API.",
    "payment_actions": "Authorization, capture, refund and void actions for each payment.",
    "customers": "Customer records referenced by your payments.",
    "instruments": "Stored payment instruments referenced by your payments.",
}


@SourceRegistry.register
class CheckoutComSource(ResumableSource[CheckoutComSourceConfig, CheckoutComResumeConfig]):
    # The catalog listed without credentials is the static part (disputes + reports);
    # the per-report-type tables need credentials to discover, so `get_schemas` only
    # reaches the API when the config carries real keys.
    lists_tables_without_credentials = True

    api_docs_url = "https://api-reference.checkout.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CHECKOUTCOM

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # The 403 matches are path-qualified so an expired signed storage URL (a different
        # host) stays retryable, and so each endpoint gets the right scope hint. Action and
        # payment-detail lookups match on `/payments/pay_` because `/payments` alone would
        # also match the search path.
        errors: dict[str, str | None] = {
            # Permanent token-exchange failures (invalid_client, bad request, …) all carry
            # the framework's stable marker; transient 429/5xx token errors don't.
            OAUTH2_PERMANENT_ERROR_MARKER: "Checkout.com authentication failed. Please check your access key ID and secret (and that they match the selected environment).",
            # A customers/instruments run whose references all lack a fetchable identifier
            # fails identically on every retry: the account's payments simply don't carry
            # ids or emails for the records this table would hold.
            UNRESOLVED_REFERENCES_MARKER: (
                "Checkout.com returned payments whose customer or instrument references carry no usable "
                "identifier, so the referenced records can't be fetched and this table can't be filled. "
                "Re-enable syncing to skip those payments and continue with newer ones."
            ),
        }
        for host in ("https://api.checkout.com", "https://api.sandbox.checkout.com"):
            errors[f"403 Client Error: Forbidden for url: {host}/disputes"] = (
                "Checkout.com denied access. Please check that your access key has the disputes scope."
            )
            errors[f"403 Client Error: Forbidden for url: {host}/reports"] = (
                "Checkout.com denied access to reports. Please check that your access key has the reports scope."
            )
            # Unlike disputes, a freshly-minted token still gets 401 (not 403) from the
            # reports endpoint when the access key lacks the reports scope, so a mid-sync
            # re-mint (which handles a genuinely expired token elsewhere) never resolves it.
            errors[f"401 Client Error: Unauthorized for url: {host}/reports"] = (
                "Checkout.com denied access to reports. Please check that your access key has the reports scope."
            )
            errors[f"403 Client Error: Forbidden for url: {host}/payments/search"] = (
                "Checkout.com denied access to payments search. Please check that your access key has the payments scope."
            )
            errors[f"403 Client Error: Forbidden for url: {host}/payments/pay_"] = (
                "Checkout.com denied access to payment details. Please check that your access key has the gateway scope."
            )
            errors[f"403 Client Error: Forbidden for url: {host}/customers"] = (
                "Checkout.com denied access to customers. Please check that your access key has the vault scope."
            )
            errors[f"403 Client Error: Forbidden for url: {host}/instruments"] = (
                "Checkout.com denied access to instruments. Please check that your access key has the vault scope."
            )
        return errors

    def get_retryable_errors(self) -> set[str]:
        # `/payments/search` has no internal retry wrapper — the shared session's retry adapter only
        # covers GET/HEAD/OPTIONS, since POSTs aren't safe to blindly retry in general — but a search
        # request has no side effects, so a 503 here is a transient upstream blip, not a bug. Temporal
        # retries the whole activity, so this stays out of tracked exception noise. Matched on the full
        # status+reason phrase (not just "for url: .../payments/search") so a 4xx on the same endpoint —
        # which would be a real bug, e.g. a malformed request body — is never swallowed the same way.
        return {
            "503 Server Error: Service Unavailable for url: https://api.checkout.com/payments/search",
            "503 Server Error: Service Unavailable for url: https://api.sandbox.checkout.com/payments/search",
            # A run that stops at its per-run API budget is incomplete, not broken. Every
            # window it finished is checkpointed, so the retry resumes there and covers more
            # ground; a long backfill converges over several attempts. It has to raise rather
            # than return so the schema never reports Completed over an unfilled range.
            SYNC_BUDGET_EXCEEDED_MARKER,
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CHECKOUT_COM,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Checkout.com",
            caption="""Enter your Checkout.com API access keys to pull your payments data into the PostHog Data warehouse.

Create an access key in the [Checkout.com dashboard](https://dashboard.checkout.com/) under Settings > Access keys. Grant it the scopes for the tables you want to sync: `disputes`, `reports`, `payments` (search), `gateway` (payment actions and instruments), and `vault` (customers and instruments).

Payments, payment actions, customers and instruments sync from the payments search API. It reaches back 90 days by default. Set a start date to sync more history. Financial reporting data (financial actions, payouts, balances) syncs from your generated report files: each report type available for your account becomes a table. If no report tables show up, set up scheduled reports in your Checkout.com dashboard first.""",
            iconPath="/static/services/checkout_com.png",
            docsUrl="https://posthog.com/docs/cdp/sources/checkout-com",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue="production",
                        options=[
                            SourceFieldSelectConfigOption(label="Production", value="production"),
                            SourceFieldSelectConfigOption(label="Sandbox", value="sandbox"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Access key ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="ack_...",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="Access key secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="2024-01-01",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CheckoutComSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Disputes support a server-side `from` filter on last_update; the reports
        # tables filter on report creation time and the payments tables on payment
        # request time. Boundary re-reads on those inclusive range filters make append
        # unsafe, so everything except disputes is merge-only.
        schemas = build_endpoint_schemas(
            (*ENDPOINTS, REPORTS_METADATA_ENDPOINT, *PAYMENTS_ENDPOINTS),
            {
                "disputes": _DISPUTES_INCREMENTAL_FIELDS,
                REPORTS_METADATA_ENDPOINT: _REPORTS_INCREMENTAL_FIELDS,
                **_PAYMENTS_INCREMENTAL_FIELDS,
            },
            None,
            merge_only=(REPORTS_METADATA_ENDPOINT, *PAYMENTS_ENDPOINTS),
            descriptions={
                REPORTS_METADATA_ENDPOINT: "Generated report files available for your account.",
                **_PAYMENTS_ENDPOINT_DESCRIPTIONS,
            },
        )

        # One table per report type the account generates. Discovery needs the API, so
        # the credential-free path (public docs, placeholder configs) stays static.
        if config.client_id and config.client_secret:
            try:
                discovered = discover_report_types(config.environment, config.client_id, config.client_secret)
            except requests.HTTPError as e:
                # 401/403 from the reports endpoint means the access key lacks the
                # reports scope, which is a valid permanent configuration whose correct
                # listing is the static catalog. Every other failure must propagate:
                # degrading to the static catalog on a transient error would make
                # scheduled discovery prune the report-type schemas it discovered on
                # earlier runs (sync_old_schemas_with_new_schemas soft-deletes or
                # disables stored names the listing no longer returns).
                status = e.response.status_code if e.response is not None else None
                if status not in (401, 403):
                    raise
                logger.warning(
                    "Checkout.com report type discovery denied; listing the static catalog only",
                    team_id=team_id,
                    status=status,
                )
                discovered = {}
            for table_name in sorted(discovered):
                schemas.append(
                    SourceSchema(
                        name=table_name,
                        supports_incremental=True,
                        supports_append=False,
                        incremental_fields=_REPORT_ROWS_INCREMENTAL_FIELDS,
                        description=f'Rows from your generated "{discovered[table_name]}" report files.',
                    )
                )

        if names is not None:
            names_set = set(names)
            schemas = [schema for schema in schemas if schema.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: CheckoutComSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_checkout_credentials(config.environment, config.client_id, config.client_secret):
            return True, None

        return False, "Invalid Checkout.com access keys"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CheckoutComResumeConfig]:
        return ResumableSourceManager[CheckoutComResumeConfig](inputs, CheckoutComResumeConfig)

    def source_for_pipeline(
        self,
        config: CheckoutComSourceConfig,
        resumable_source_manager: ResumableSourceManager[CheckoutComResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name in ENDPOINTS:
            return checkout_com_source(
                environment=config.environment,
                client_id=config.client_id,
                client_secret=config.client_secret,
                endpoint=inputs.schema_name,
                team_id=inputs.team_id,
                job_id=inputs.job_id,
                resumable_source_manager=resumable_source_manager,
                should_use_incremental_field=inputs.should_use_incremental_field,
                db_incremental_field_last_value=inputs.db_incremental_field_last_value
                if inputs.should_use_incremental_field
                else None,
            )

        if inputs.schema_name in PAYMENTS_ENDPOINTS:
            return checkout_com_payments_source(
                environment=config.environment,
                client_id=config.client_id,
                client_secret=config.client_secret,
                schema_name=inputs.schema_name,
                logger=inputs.logger,
                resumable_source_manager=resumable_source_manager,
                start_date=config.start_date,
                should_use_incremental_field=inputs.should_use_incremental_field,
                db_incremental_field_last_value=inputs.db_incremental_field_last_value
                if inputs.should_use_incremental_field
                else None,
            )

        return checkout_com_reports_source(
            environment=config.environment,
            client_id=config.client_id,
            client_secret=config.client_secret,
            schema_name=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
