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

from products.warehouse_sources.backend.temporal.data_imports.sources.bill_com.bill_com import (
    BillComResumeConfig,
    bill_com_source,
    validate_credentials as validate_bill_com_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bill_com.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.billcom import (
    BillComSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BillComSource(ResumableSource[BillComSourceConfig, BillComResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://developer.bill.com/reference/api-reference-overview"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BILLCOM

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "BILL sign-in failed": "BILL could not sign you in. Please check your email, password, organization ID, and developer key.",
            "BILL sign-in did not return a session ID": "BILL did not start an API session. Please check your developer key and try again.",
            "401 Client Error: Unauthorized for url: https://gateway": "Your BILL API session could not be renewed. Please check your credentials and reconnect.",
            "403 Client Error: Forbidden for url: https://gateway": "Your BILL user does not have access to this data. Please check the user's permissions and try again.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.bill_com.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BILL_COM,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="BILL (formerly Bill.com)",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["bill.com", "accounts payable", "accounts receivable", "ap", "ar"],
            caption="""Connect BILL to pull your accounts payable and receivable data into the PostHog Data warehouse.

Create a developer key in your [BILL developer account](https://developer.bill.com/docs/bill-keys-tokens), then enter the email and password you sign in with, your organization ID, and that developer key. PostHog uses them to start an API session for each sync.

BILL Spend & Expense data is not included — it uses a separate API token.""",
            iconPath="/static/services/bill_com.png",
            docsUrl="https://posthog.com/docs/cdp/sources/bill-com",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="username",
                        label="Email",
                        type=SourceFieldInputConfigType.EMAIL,
                        required=True,
                        placeholder="you@company.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="password",
                        label="Password",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="organization_id",
                        label="Organization ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="dev_key",
                        label="Developer key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
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
                ],
            ),
        )

    def get_schemas(
        self,
        config: BillComSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: BillComSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_bill_com_credentials(
            username=config.username,
            password=config.password,
            organization_id=config.organization_id,
            dev_key=config.dev_key,
            environment=config.environment,
            api_version=self.resolve_api_version(api_version),
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BillComResumeConfig]:
        return ResumableSourceManager[BillComResumeConfig](inputs, BillComResumeConfig)

    def source_for_pipeline(
        self,
        config: BillComSourceConfig,
        resumable_source_manager: ResumableSourceManager[BillComResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return bill_com_source(
            username=config.username,
            password=config.password,
            organization_id=config.organization_id,
            dev_key=config.dev_key,
            environment=config.environment,
            api_version=self.resolve_api_version(inputs.api_version),
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
