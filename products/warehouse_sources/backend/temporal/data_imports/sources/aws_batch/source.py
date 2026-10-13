from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_batch.aws_batch import (
    AwsBatchResumeConfig,
    aws_batch_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_batch.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_batch.settings import (
    BATCH_API_VERSION,
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    NON_RETRYABLE_ERRORS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsbatch import (
    AwsBatchSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsBatchSource(ResumableSource[AwsBatchSourceConfig, AwsBatchResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = (BATCH_API_VERSION,)
    default_version = BATCH_API_VERSION
    api_docs_url = "https://docs.aws.amazon.com/batch/latest/APIReference/Welcome.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSBATCH

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return dict(NON_RETRYABLE_ERRORS)

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AwsBatchSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, descriptions=ENDPOINT_DESCRIPTIONS)

    def validate_credentials(
        self,
        config: AwsBatchSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, schema_name, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AwsBatchResumeConfig]:
        return ResumableSourceManager(inputs, AwsBatchResumeConfig)

    def source_for_pipeline(
        self,
        config: AwsBatchSourceConfig,
        resumable_source_manager: ResumableSourceManager[AwsBatchResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aws_batch_source(
            config, inputs.schema_name, resumable_source_manager, self.resolve_api_version(inputs.api_version)
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSBATCH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="AWS Batch",
            caption=(
                "Sync AWS Batch jobs and resources from one region. "
                "Grant `batch:DescribeJobQueues`, `batch:ListJobs`, and `batch:DescribeJobs` to read jobs. "
                "Grant `batch:DescribeComputeEnvironments` and `batch:DescribeJobDefinitions` to read those tables. "
                "Enter an access key ID and secret access key. Add a session token for temporary credentials. "
                "All tables use full refresh so later job status changes remain visible. "
                "The jobs table includes jobs that AWS still retains in existing queues. "
                "Array children and individual nodes are not expanded."
            ),
            iconPath="/static/services/aws_batch.png",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["aws", "batch", "jobs", "compute"],
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
                        placeholder="",
                        secret=True,
                        caption="Required for temporary credentials. Replace these credentials when the session token expires.",
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
