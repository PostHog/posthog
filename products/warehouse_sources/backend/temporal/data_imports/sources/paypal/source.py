from typing import Optional, cast

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

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.paypal import PayPalSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.paypal.paypal import (
    PayPalResumeConfig,
    paypal_source,
    validate_credentials as validate_paypal_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paypal.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    TRANSACTIONS_INCREMENTAL_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PayPalSource(ResumableSource[PayPalSourceConfig, PayPalResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # PayPal versions each resource independently (/v1/reporting, /v2/invoicing) rather than
    # offering an account-wide version choice, so there is nothing to pin.
    api_docs_url = "https://developer.paypal.com/api/rest/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PAYPAL

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api-m.paypal.com/v1/oauth2/token": "PayPal rejected your app credentials. Check the client ID and secret, and that they belong to the live environment.",
            "401 Client Error: Unauthorized for url: https://api-m.sandbox.paypal.com/v1/oauth2/token": "PayPal rejected your app credentials. Check the client ID and secret, and that they belong to the sandbox environment.",
            "400 Client Error: Bad Request for url: https://api-m.paypal.com/v1/oauth2/token": "PayPal could not issue a token for your app. Check the client ID and secret, and that they belong to the live environment.",
            "400 Client Error: Bad Request for url: https://api-m.sandbox.paypal.com/v1/oauth2/token": "PayPal could not issue a token for your app. Check the client ID and secret, and that they belong to the sandbox environment.",
            "403 Client Error: Forbidden for url": "Your PayPal app is not allowed to call this API. In the PayPal developer dashboard, enable the features this source needs (Transaction Search, Invoicing, Subscriptions, Disputes) on the app.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.paypal.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: PayPalSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)
        for schema in schemas:
            if schema.name == "transactions":
                # A transaction can take up to three hours to become searchable, so each
                # incremental run re-reads a trailing window (the merge dedupes on the id).
                schema.default_incremental_lookback_seconds = TRANSACTIONS_INCREMENTAL_LOOKBACK_SECONDS
        return schemas

    def validate_credentials(
        self,
        config: PayPalSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_paypal_credentials(config.environment, config.client_id, config.client_secret)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PayPalResumeConfig]:
        return ResumableSourceManager[PayPalResumeConfig](inputs, PayPalResumeConfig)

    def source_for_pipeline(
        self,
        config: PayPalSourceConfig,
        resumable_source_manager: ResumableSourceManager[PayPalResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return paypal_source(
            environment=config.environment,
            client_id=config.client_id,
            client_secret=config.client_secret,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PAY_PAL,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="PayPal",
            caption="""Import transactions, balances, disputes, invoices, subscription plans, and catalog products from your PayPal business account.

Create a REST app in the [PayPal developer dashboard](https://developer.paypal.com/dashboard/applications) and paste its client ID and secret. Enable Transaction Search on the app so transaction history can sync. PayPal keeps three years of it. Disputes reach back 180 days.""",
            docsUrl="https://posthog.com/docs/cdp/sources/paypal",
            iconPath="/static/services/paypal.png",
            keywords=["payments", "checkout"],
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue="live",
                        options=[
                            SourceFieldSelectConfigOption(label="Live", value="live"),
                            SourceFieldSelectConfigOption(label="Sandbox", value="sandbox"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="Client secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
