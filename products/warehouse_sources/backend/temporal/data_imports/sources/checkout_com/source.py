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

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.checkout_com import (
    ENDPOINTS,
    CheckoutComResumeConfig,
    checkout_com_source,
    validate_credentials as validate_checkout_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CheckoutComSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalField, IncrementalFieldType

_DISPUTES_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "last_update",
        "type": IncrementalFieldType.DateTime,
        "field": "last_update",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@SourceRegistry.register
class CheckoutComSource(ResumableSource[CheckoutComSourceConfig, CheckoutComResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    api_docs_url = "https://api-reference.checkout.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CHECKOUTCOM

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://access.checkout.com": "Checkout.com authentication failed. Please check your access key ID and secret.",
            "401 Client Error: Unauthorized for url: https://access.sandbox.checkout.com": "Checkout.com authentication failed. Please check your access key ID and secret (and that they match the selected environment).",
            "400 Client Error: Bad Request for url: https://access.checkout.com": "Checkout.com authentication failed. Please check your access key ID and secret.",
            "400 Client Error: Bad Request for url: https://access.sandbox.checkout.com": "Checkout.com authentication failed. Please check your access key ID and secret.",
            "403 Client Error: Forbidden for url: https://api.checkout.com": "Checkout.com denied access. Please check that your access key has the disputes scope.",
            "403 Client Error: Forbidden for url: https://api.sandbox.checkout.com": "Checkout.com denied access. Please check that your access key has the disputes scope.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CHECKOUT_COM,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Checkout.com",
            caption="""Enter your Checkout.com API access keys to pull your disputes data into the PostHog Data warehouse.

Create an access key in the [Checkout.com dashboard](https://dashboard.checkout.com/) under Settings > Access keys with the `disputes` scope. Bulk payment data isn't listable via the API (it ships as report files), so this source currently syncs disputes.""",
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
    ) -> list[SourceSchema]:
        # Disputes support a server-side `from` filter on last_update.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=True,
                supports_append=True,
                incremental_fields=list(_DISPUTES_INCREMENTAL_FIELDS),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: CheckoutComSourceConfig, team_id: int, schema_name: Optional[str] = None
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
        return checkout_com_source(
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
