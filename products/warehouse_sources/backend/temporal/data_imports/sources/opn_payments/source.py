from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.opnpayments import (
    OpnPaymentsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opn_payments.opn_payments import (
    OpnPaymentsResumeConfig,
    opn_payments_source,
    validate_credentials as validate_opn_payments_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opn_payments.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OpnPaymentsSource(ResumableSource[OpnPaymentsSourceConfig, OpnPaymentsResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("2019-05-29",)
    default_version = "2019-05-29"
    api_docs_url = "https://docs.omise.co/api-versioning"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OPNPAYMENTS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Opn Payments secret key is invalid. Check the key and try again.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.opn_payments.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: OpnPaymentsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: OpnPaymentsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_opn_payments_credentials(config.secret_key, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OpnPaymentsResumeConfig]:
        return ResumableSourceManager[OpnPaymentsResumeConfig](inputs, OpnPaymentsResumeConfig)

    def source_for_pipeline(
        self,
        config: OpnPaymentsSourceConfig,
        resumable_source_manager: ResumableSourceManager[OpnPaymentsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return opn_payments_source(
            secret_key=config.secret_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            api_version=self.resolve_api_version(inputs.api_version),
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OPN_PAYMENTS,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Opn Payments (formerly Omise)",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="Enter your Opn Payments (Omise) secret key to sync charges, customers, transfers, "
            "and more into the PostHog Data warehouse. Find your secret key in the Opn Payments "
            "dashboard under **Keys**.",
            docsUrl="https://posthog.com/docs/cdp/sources/opn-payments",
            iconPath="/static/services/opn_payments.png",
            keywords=["omise", "thailand"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="secret_key",
                        label="Secret key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="skey_test_...",
                        secret=True,
                    ),
                ],
            ),
        )
