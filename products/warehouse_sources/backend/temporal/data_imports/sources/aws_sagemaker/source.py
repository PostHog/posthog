from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_sagemaker.aws_sagemaker import (
    ERROR_MESSAGES,
    AwsSagemakerResumeConfig,
    aws_sagemaker_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_sagemaker.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_sagemaker.settings import (
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SAGEMAKER_API_VERSION,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awssagemaker import (
    AwsSagemakerSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsSagemakerSource(ResumableSource[AwsSagemakerSourceConfig, AwsSagemakerResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = (SAGEMAKER_API_VERSION,)
    default_version = SAGEMAKER_API_VERSION
    api_docs_url = "https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_Operations.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSSAGEMAKER

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {f"AWS SageMaker request failed: {code}": message for code, message in ERROR_MESSAGES.items()}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AwsSagemakerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, descriptions=ENDPOINT_DESCRIPTIONS)

    def validate_credentials(
        self,
        config: AwsSagemakerSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, schema_name, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AwsSagemakerResumeConfig]:
        return ResumableSourceManager(inputs, AwsSagemakerResumeConfig)

    def source_for_pipeline(
        self,
        config: AwsSagemakerSourceConfig,
        resumable_source_manager: ResumableSourceManager[AwsSagemakerResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aws_sagemaker_source(
            config,
            inputs.schema_name,
            self.resolve_api_version(inputs.api_version),
            resumable_source_manager,
            inputs.should_use_incremental_field,
            inputs.db_incremental_field_last_value,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSSAGEMAKER,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="AWS SageMaker",
            caption=(
                "Sync SageMaker resources from one AWS region. "
                "Grant these IAM permissions for the tables you select: "
                "`sagemaker:ListTrainingJobs`, `sagemaker:DescribeTrainingJob`, "
                "`sagemaker:ListProcessingJobs`, `sagemaker:DescribeProcessingJob`, "
                "`sagemaker:ListEndpoints`, `sagemaker:DescribeEndpoint`, "
                "`sagemaker:ListModels`, and `sagemaker:DescribeModel`. "
                "Jobs and endpoints use full refresh to capture status changes. "
                "Models also support incremental sync by creation time."
            ),
            iconPath="/static/services/aws_sagemaker.png",
            releaseStatus=ReleaseStatus.ALPHA,
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
                        secret=True,
                        caption="Temporary credentials require a session token. Scheduled syncs fail when the token expires.",
                    ),
                    SourceFieldInputConfig(
                        name="region",
                        label="AWS region",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="us-east-1",
                        secret=False,
                    ),
                ],
            ),
        )
