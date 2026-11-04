from typing import cast

from products.warehouse_sources.sources.aws_batch._config import AwsBatchSourceConfig
from products.warehouse_sources.sources.aws_batch.aws_batch import (
    AwsBatchResumeConfig,
    aws_batch_source,
    validate_credentials,
)
from products.warehouse_sources.sources.aws_batch.canonical_descriptions import CANONICAL_DESCRIPTIONS
from products.warehouse_sources.sources.aws_batch.settings import (
    AWS_SESSION_ACTIONS,
    BATCH_API_VERSION,
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    NON_RETRYABLE_ERRORS,
)
from products.warehouse_sources.sources.sdk import (
    AWS_AUTH_NON_RETRYABLE_ERRORS,
    AWS_FLAT_STORED_SELECTS,
    AwsAuthError,
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    aws_auth_field,
    build_endpoint_schemas,
    detect,
    resolve_aws_credentials,
)


@SourceRegistry.register
class AwsBatchSource(ResumableSource[AwsBatchSourceConfig, AwsBatchResumeConfig]):
    codebase_detection = detect(
        env=("^(AWS_BATCH|AWSBATCH)_",),
        npm=("@aws-sdk/client-batch",),
        cargo=("aws-sdk-batch",),
        go=("github.com/aws/aws-sdk-go-v2/service/batch",),
        maven=("software.amazon.awssdk:batch", "com.amazonaws:aws-java-sdk-batch"),
        rubygems=("aws-sdk-batch",),
    )

    lists_tables_without_credentials = True
    supported_versions = (BATCH_API_VERSION,)
    default_version = BATCH_API_VERSION
    api_docs_url = "https://docs.aws.amazon.com/batch/latest/APIReference/Welcome.html"

    flat_stored_selects = AWS_FLAT_STORED_SELECTS
    aws_session_actions = AWS_SESSION_ACTIONS
    credential_kind = "aws-batch"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSBATCH

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {**AWS_AUTH_NON_RETRYABLE_ERRORS, **NON_RETRYABLE_ERRORS}

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
        try:
            credentials = resolve_aws_credentials(config.aws_auth, team_id, AWS_SESSION_ACTIONS)
        except AwsAuthError as error:
            return False, str(error)
        return validate_credentials(config, credentials, schema_name, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AwsBatchResumeConfig]:
        return ResumableSourceManager(inputs, AwsBatchResumeConfig)

    def source_for_pipeline(
        self,
        config: AwsBatchSourceConfig,
        resumable_source_manager: ResumableSourceManager[AwsBatchResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aws_batch_source(
            config,
            resolve_aws_credentials(config.aws_auth, inputs.team_id, AWS_SESSION_ACTIONS),
            inputs.schema_name,
            resumable_source_manager,
            self.resolve_api_version(inputs.api_version),
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSBATCH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="AWS Batch",
            caption=(
                "Sync AWS Batch jobs and resources from one region. "
                "Grant `batch:DescribeJobQueues`, `batch:ListJobs`, and `batch:DescribeJobs` to read jobs and job children. "
                "Grant `batch:DescribeJobQueues` and `batch:ListServiceJobs` to read service jobs. "
                "Grant `batch:DescribeComputeEnvironments` and `batch:DescribeJobDefinitions` to read those tables. "
                "Grant `batch:ListSchedulingPolicies` and `batch:DescribeSchedulingPolicies` to read scheduling policies. "
                "Grant `batch:ListConsumableResources` and `batch:DescribeConsumableResource` to read consumable resources. "
                "Connect with an IAM role, or with an access key ID and secret access key. Add a session token for temporary credentials. "
                "All tables use full refresh so later job status changes remain visible. "
                "The jobs and service jobs tables include jobs that AWS still retains in existing queues. "
                "The job children table includes the children of array jobs and the nodes of multi-node parallel jobs."
            ),
            iconPath="/static/services/aws_batch.png",
            releaseStatus=ReleaseStatus.BETA,
            keywords=["aws", "batch", "jobs", "compute"],
            fields=cast(
                list[FieldType],
                [
                    aws_auth_field(),
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
