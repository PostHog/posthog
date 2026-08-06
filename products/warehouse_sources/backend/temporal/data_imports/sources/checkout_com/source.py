from typing import Optional, cast

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
        # host) stays retryable, and so disputes and reports each get the right scope hint.
        return {
            # Permanent token-exchange failures (invalid_client, bad request, …) all carry
            # the framework's stable marker; transient 429/5xx token errors don't.
            OAUTH2_PERMANENT_ERROR_MARKER: "Checkout.com authentication failed. Please check your access key ID and secret (and that they match the selected environment).",
            "403 Client Error: Forbidden for url: https://api.checkout.com/disputes": "Checkout.com denied access. Please check that your access key has the disputes scope.",
            "403 Client Error: Forbidden for url: https://api.sandbox.checkout.com/disputes": "Checkout.com denied access. Please check that your access key has the disputes scope.",
            "403 Client Error: Forbidden for url: https://api.checkout.com/reports": "Checkout.com denied access to reports. Please check that your access key has the reports scope.",
            "403 Client Error: Forbidden for url: https://api.sandbox.checkout.com/reports": "Checkout.com denied access to reports. Please check that your access key has the reports scope.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CHECKOUT_COM,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Checkout.com",
            caption="""Enter your Checkout.com API access keys to pull your payments data into the PostHog Data warehouse.

Create an access key in the [Checkout.com dashboard](https://dashboard.checkout.com/) under Settings > Access keys with the `disputes` and `reports` scopes.

Disputes sync from the Disputes API. Bulk payment data (payments, financial actions, payouts, balances) syncs from your generated report files: each report type available for your account becomes a table. If no report tables show up, set up scheduled reports in your Checkout.com dashboard first.""",
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
        # tables filter on report creation time. Boundary re-reads on the inclusive
        # `created_after` filter make append unsafe for them, so they are merge-only.
        schemas = build_endpoint_schemas(
            (*ENDPOINTS, REPORTS_METADATA_ENDPOINT),
            {
                "disputes": _DISPUTES_INCREMENTAL_FIELDS,
                REPORTS_METADATA_ENDPOINT: _REPORTS_INCREMENTAL_FIELDS,
            },
            None,
            merge_only=(REPORTS_METADATA_ENDPOINT,),
            descriptions={REPORTS_METADATA_ENDPOINT: "Generated report files available for your account."},
        )

        # One table per report type the account generates. Discovery needs the API, so
        # the credential-free path (public docs, placeholder configs) stays static, and
        # any discovery failure degrades to the static catalog instead of breaking the
        # schema listing.
        if config.client_id and config.client_secret:
            try:
                discovered = discover_report_types(config.environment, config.client_id, config.client_secret)
            except Exception:
                logger.exception("Checkout.com report type discovery failed", team_id=team_id)
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
