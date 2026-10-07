from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_compute_optimizer.aws_compute_optimizer import (
    AwsComputeOptimizerResumeConfig,
    aws_compute_optimizer_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_compute_optimizer.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_compute_optimizer.settings import (
    API_DOCS_URL,
    API_VERSION,
    ENDPOINTS,
    ERROR_MESSAGES,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awscomputeoptimizer import (
    AwsComputeOptimizerSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsComputeOptimizerSource(ResumableSource[AwsComputeOptimizerSourceConfig, AwsComputeOptimizerResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSCOMPUTEOPTIMIZER

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {f"AWS Compute Optimizer request failed: {code}": message for code, message in ERROR_MESSAGES.items()}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AwsComputeOptimizerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS, {}, names, descriptions={name: endpoint.description for name, endpoint in ENDPOINTS.items()}
        )

    def validate_credentials(
        self,
        config: AwsComputeOptimizerSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, schema_name, self.resolve_api_version(api_version))

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[AwsComputeOptimizerResumeConfig]:
        return ResumableSourceManager(inputs, AwsComputeOptimizerResumeConfig)

    def source_for_pipeline(
        self,
        config: AwsComputeOptimizerSourceConfig,
        resumable_source_manager: ResumableSourceManager[AwsComputeOptimizerResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aws_compute_optimizer_source(
            config, inputs.schema_name, resumable_source_manager, self.resolve_api_version(inputs.api_version)
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSCOMPUTEOPTIMIZER,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="AWS Compute Optimizer",
            caption="""Sync AWS Compute Optimizer recommendations for the connected account in one AWS region.

Enable Compute Optimizer for this account before you sync.
Grant `compute-optimizer:GetEnrollmentStatus` to check enrollment.
Grant these permissions for the tables you select:
- `compute-optimizer:GetEC2InstanceRecommendations`
- `compute-optimizer:GetAutoScalingGroupRecommendations`
- `compute-optimizer:GetLambdaFunctionRecommendations`
- `compute-optimizer:GetECSServiceRecommendations`
- `compute-optimizer:GetEBSVolumeRecommendations`
- `compute-optimizer:GetRecommendationSummaries`

Each sync replaces the current recommendations. This source does not keep recommendation history.""",
            iconPath="/static/services/aws_compute_optimizer.png",
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
                        secret=True,
                        placeholder="",
                    ),
                    SourceFieldInputConfig(
                        name="aws_session_token",
                        label="AWS session token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        secret=True,
                        placeholder="Only needed for temporary credentials",
                        caption="Required for temporary credentials. Update the credentials before the token expires.",
                    ),
                    SourceFieldInputConfig(
                        name="region",
                        label="AWS region",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        secret=False,
                        placeholder="us-east-1",
                        caption="Sync recommendations from this region. The default is us-east-1.",
                    ),
                ],
            ),
        )
