from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.aws_auth import (
    AWS_AUTH_NON_RETRYABLE_ERRORS,
    AWS_FLAT_STORED_SELECTS,
    AwsAuthError,
    aws_auth_field,
    resolve_aws_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamodb.dynamodb import (
    DynamoDBClient,
    DynamoDBResumeConfig,
    dynamodb_source,
    get_table_schemas,
    validate_credentials as validate_dynamodb_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamodb.settings import (
    DYNAMODB_API_VERSION,
    NON_RETRYABLE_ERROR_MESSAGES,
    RETRYABLE_ERROR_CODES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dynamodb import (
    DynamoDBSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DynamoDBSource(ResumableSource[DynamoDBSourceConfig, DynamoDBResumeConfig]):
    codebase_detection = detect(
        npm=("@aws-sdk/client-dynamodb", "@aws-sdk/lib-dynamodb", "@aws-sdk/util-dynamodb", "dynamoose"),
        pypi=("pynamodb",),
        cargo=("aws-sdk-dynamodb",),
        go=("github.com/aws/aws-sdk-go-v2/service/dynamodb",),
        maven=(
            "software.amazon.awssdk:dynamodb",
            "software.amazon.awssdk:dynamodb-enhanced",
            "software.amazon.awssdk:dynamodbdocument-v1",
            "software.amazon.awssdk:dynamodbmapper-v1",
        ),
        rubygems=("aws-sdk-dynamodb",),
    )

    supported_versions = (DYNAMODB_API_VERSION,)
    default_version = DYNAMODB_API_VERSION
    api_docs_url = "https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/Welcome.html"

    flat_stored_selects = AWS_FLAT_STORED_SELECTS

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DYNAMODB

    @property
    def credential_kind(self) -> str | None:
        return "dynamodb"

    @property
    def connection_host_fields(self) -> list[str]:
        # The region picks the endpoint the signed request — and so the customer's key — is sent to.
        return ["aws_region"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {**AWS_AUTH_NON_RETRYABLE_ERRORS, **NON_RETRYABLE_ERROR_MESSAGES}

    def get_retryable_errors(self) -> set[str]:
        return set(RETRYABLE_ERROR_CODES)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DYNAMODB,
            category=DataWarehouseSourceCategory.DATABASES,
            label="DynamoDB",
            caption="""Connect an IAM role or an access key with read access to DynamoDB to import your tables into the PostHog Data warehouse.

Create an IAM role or user whose policy allows `dynamodb:ListTables`, `dynamodb:DescribeTable` and `dynamodb:Scan`. Connect with the role, or paste the user's access key below. Tables are read with a full table scan, so every sync uses read capacity on the table.""",
            iconPath="/static/services/dynamodb.png",
            docsUrl="https://posthog.com/docs/cdp/sources/dynamodb",
            releaseStatus=ReleaseStatus.GA,
            keywords=["aws", "nosql"],
            fields=cast(
                list[FieldType],
                [
                    aws_auth_field(),
                    SourceFieldInputConfig(
                        name="aws_region",
                        label="AWS region",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="us-east-1",
                        secret=False,
                    ),
                ],
            ),
        )

    def _client(self, config: DynamoDBSourceConfig, team_id: int, api_version: str | None = None) -> DynamoDBClient:
        return DynamoDBClient(
            credentials=resolve_aws_credentials(config.aws_auth, team_id),
            region=config.aws_region,
            api_version=self.resolve_api_version(api_version),
        )

    def get_schemas(
        self,
        config: DynamoDBSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return get_table_schemas(self._client(config, team_id, api_version), with_counts=with_counts, names=names)

    def validate_credentials(
        self,
        config: DynamoDBSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            credentials = resolve_aws_credentials(config.aws_auth, team_id)
        except AwsAuthError as error:
            return False, str(error)
        return validate_dynamodb_credentials(
            credentials=credentials,
            region=config.aws_region,
            api_version=self.resolve_api_version(api_version),
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DynamoDBResumeConfig]:
        return ResumableSourceManager[DynamoDBResumeConfig](inputs, DynamoDBResumeConfig)

    def source_for_pipeline(
        self,
        config: DynamoDBSourceConfig,
        resumable_source_manager: ResumableSourceManager[DynamoDBResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return dynamodb_source(
            credentials=resolve_aws_credentials(config.aws_auth, inputs.team_id),
            region=config.aws_region,
            table_name=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            api_version=self.resolve_api_version(inputs.api_version),
        )
