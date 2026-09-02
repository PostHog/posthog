from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_explorer.aws_cost_explorer import (
    AwsCostExplorerResumeConfig,
    aws_cost_explorer_source,
    validate_credentials as validate_aws_cost_explorer_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_explorer.settings import (
    ENDPOINT_DESCRIPTIONS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awscostexplorer import (
    AwsCostExplorerSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsCostExplorerSource(ResumableSource[AwsCostExplorerSourceConfig, AwsCostExplorerResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_Operations_AWS_Cost_Explorer_Service.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSCOSTEXPLORER

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "AWS Cost Explorer request failed: UnrecognizedClientException": "AWS rejected the access key. Please check the access key ID and secret access key, and that the key is still active.",
            "AWS Cost Explorer request failed: InvalidClientTokenId": "AWS rejected the access key. Please check the access key ID and secret access key, and that the key is still active.",
            "AWS Cost Explorer request failed: SignatureDoesNotMatch": "AWS rejected the request signature. Please re-enter the secret access key.",
            "AWS Cost Explorer request failed: InvalidSignatureException": "AWS rejected the request signature. If you are using temporary credentials, the session token has expired.",
            "AWS Cost Explorer request failed: ExpiredTokenException": "The AWS session token has expired. Please reconnect with fresh credentials.",
            "AWS Cost Explorer request failed: AccessDeniedException": "These AWS credentials are missing Cost Explorer permissions. Grant ce:GetCostAndUsage, ce:GetReservationUtilization and ce:GetSavingsPlansUtilization to the IAM user or role.",
            "AWS Cost Explorer request failed: DataUnavailableException": "AWS has no Cost Explorer data for the requested dates. Cost Explorer has to be enabled on the account, and it can take up to 24 hours to prepare data.",
            "AWS Cost Explorer request failed: BillExpirationException": "The requested dates are older than the data AWS keeps. Move the start date forward and try again.",
            "AWS access key ID and secret access key are required": "Enter both an AWS access key ID and a secret access key.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_explorer.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AwsCostExplorerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, descriptions=ENDPOINT_DESCRIPTIONS)

    def validate_credentials(
        self,
        config: AwsCostExplorerSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_aws_cost_explorer_credentials(
            config.aws_access_key_id,
            config.aws_secret_access_key,
            config.aws_session_token,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AwsCostExplorerResumeConfig]:
        return ResumableSourceManager[AwsCostExplorerResumeConfig](inputs, AwsCostExplorerResumeConfig)

    def source_for_pipeline(
        self,
        config: AwsCostExplorerSourceConfig,
        resumable_source_manager: ResumableSourceManager[AwsCostExplorerResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aws_cost_explorer_source(
            aws_access_key_id=config.aws_access_key_id,
            aws_secret_access_key=config.aws_secret_access_key,
            aws_session_token=config.aws_session_token,
            start_date=config.start_date,
            endpoint=inputs.schema_name,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            logger=inputs.logger,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AWS_COST_EXPLORER,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="AWS Cost Explorer",
            caption="""Sync your AWS cost and usage data into the PostHog Data warehouse.

Create an IAM user or role with the `ce:GetCostAndUsage`, `ce:GetReservationUtilization` and `ce:GetSavingsPlansUtilization` permissions, then paste its access key ID and secret access key. Add a session token too if you are using temporary credentials.

Connect the management (payer) account to see spend across every member account. AWS charges $0.01 per Cost Explorer API request, so syncs ask for wide date ranges at a time.""",
            iconPath="/static/services/aws_cost_explorer.png",
            docsUrl="https://posthog.com/docs/cdp/sources/aws-cost-explorer",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["aws", "finops", "cloud spend", "cost explorer"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="aws_access_key_id",
                        label="AWS access key ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="AKIA...",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="aws_secret_access_key",
                        label="AWS secret access key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="aws_session_token",
                        label="AWS session token (only for temporary credentials)",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date (defaults to 12 months ago)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="2024-01-01",
                        secret=False,
                    ),
                ],
            ),
        )
