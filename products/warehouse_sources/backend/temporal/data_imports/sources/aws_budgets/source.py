from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_budgets.aws_budgets import (
    AwsBudgetsResumeConfig,
    aws_budgets_source,
    probe_endpoint_permissions,
    validate_credentials as validate_aws_budgets_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_budgets.settings import (
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsbudgets import (
    AwsBudgetsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsBudgetsSource(ResumableSource[AwsBudgetsSourceConfig, AwsBudgetsResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs
    # The Budgets API carries no version token in its requests: the endpoint has no version path
    # segment and the `X-Amz-Target` prefix is unversioned, so there is nothing to pin.
    api_docs_url = "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_Operations_AWS_Budgets.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSBUDGETS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "AWS STS request failed: InvalidClientTokenId": "AWS rejected the access key. Please check the access key ID and secret access key, and that the key is still active.",
            "AWS STS request failed: SignatureDoesNotMatch": "AWS rejected the request signature. Please re-enter the secret access key.",
            "AWS STS request failed: ExpiredToken": "The AWS session token has expired. Please reconnect with fresh credentials.",
            "AWS STS request failed: AccessDenied": "AWS would not confirm which account these credentials belong to. Please reconnect with a different access key.",
            "AWS Budgets request failed: UnrecognizedClientException": "AWS rejected the access key. Please check the access key ID and secret access key, and that the key is still active.",
            "AWS Budgets request failed: SignatureDoesNotMatch": "AWS rejected the request signature. Please re-enter the secret access key.",
            "AWS Budgets request failed: ExpiredTokenException": "The AWS session token has expired. Please reconnect with fresh credentials.",
            "AWS Budgets request failed: AccessDeniedException": "These AWS credentials are missing AWS Budgets read permissions. Grant budgets:DescribeBudgets, budgets:DescribeBudgetPerformanceHistory and budgets:DescribeNotificationsForBudget to the IAM user or role.",
            "AWS access key ID and secret access key are required": "Enter both an AWS access key ID and a secret access key.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.aws_budgets.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AwsBudgetsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, descriptions=ENDPOINT_DESCRIPTIONS)

    def validate_credentials(
        self,
        config: AwsBudgetsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_aws_budgets_credentials(
            config.aws_access_key_id,
            config.aws_secret_access_key,
            config.aws_session_token,
            schema_name=schema_name,
        )

    def get_endpoint_permissions(
        self, config: AwsBudgetsSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        return probe_endpoint_permissions(
            config.aws_access_key_id,
            config.aws_secret_access_key,
            config.aws_session_token,
            endpoints,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AwsBudgetsResumeConfig]:
        return ResumableSourceManager[AwsBudgetsResumeConfig](inputs, AwsBudgetsResumeConfig)

    def source_for_pipeline(
        self,
        config: AwsBudgetsSourceConfig,
        resumable_source_manager: ResumableSourceManager[AwsBudgetsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aws_budgets_source(
            aws_access_key_id=config.aws_access_key_id,
            aws_secret_access_key=config.aws_secret_access_key,
            aws_session_token=config.aws_session_token,
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
            name=SchemaExternalDataSourceType.AWS_BUDGETS,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="AWS Budgets",
            caption="""Sync your AWS budgets, their spend history, and their alert thresholds into the PostHog Data warehouse.

Create an IAM user or role with the `budgets:DescribeBudgets`, `budgets:DescribeBudgetPerformanceHistory` and `budgets:DescribeNotificationsForBudget` permissions, then paste its access key ID and secret access key. Add a session token too if you are using temporary credentials.

AWS Budgets is a global service, so there is no region to pick. PostHog looks up which account the credentials belong to and reads that account's budgets.""",
            iconPath="/static/services/aws_budgets.png",
            docsUrl="https://posthog.com/docs/cdp/sources/aws-budgets",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["aws", "finops", "cloud spend", "budgets"],
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
                        label="AWS session token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="Only needed for temporary credentials",
                        caption="Only for temporary credentials. Session tokens expire after a few hours, so scheduled syncs will fail once the token expires. Use a permanent access key (starts with AKIA) for recurring imports.",
                        secret=True,
                    ),
                ],
            ),
        )
