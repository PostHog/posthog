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
    supported_versions = (DYNAMODB_API_VERSION,)
    default_version = DYNAMODB_API_VERSION
    api_docs_url = "https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/Welcome.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DYNAMODB

    @property
    def connection_host_fields(self) -> list[str]:
        # The region picks the endpoint the signed request — and so the customer's key — is sent to.
        return ["aws_region"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return dict(NON_RETRYABLE_ERROR_MESSAGES)

    def get_retryable_errors(self) -> set[str]:
        return set(RETRYABLE_ERROR_CODES)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DYNAMO_DB,
            category=DataWarehouseSourceCategory.DATABASES,
            label="DynamoDB",
            caption="""Enter an AWS access key with read access to DynamoDB to import your tables into the PostHog Data warehouse.

Create an IAM user whose policy allows `dynamodb:ListTables`, `dynamodb:DescribeTable` and `dynamodb:Scan`, then paste its access key below. Tables are read with a full table scan, so every sync uses read capacity on the table.""",
            iconPath="/static/services/dynamodb.png",
            docsUrl="https://posthog.com/docs/cdp/sources/dynamodb",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["aws", "nosql"],
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
                        name="aws_region",
                        label="AWS region",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="us-east-1",
                        secret=False,
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

    def _client(self, config: DynamoDBSourceConfig, api_version: str | None = None) -> DynamoDBClient:
        return DynamoDBClient(
            access_key_id=config.aws_access_key_id,
            secret_access_key=config.aws_secret_access_key,
            region=config.aws_region,
            session_token=config.aws_session_token or None,
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
        return get_table_schemas(self._client(config, api_version), with_counts=with_counts, names=names)

    def validate_credentials(
        self,
        config: DynamoDBSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_dynamodb_credentials(
            access_key_id=config.aws_access_key_id,
            secret_access_key=config.aws_secret_access_key,
            region=config.aws_region,
            session_token=config.aws_session_token or None,
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
            access_key_id=config.aws_access_key_id,
            secret_access_key=config.aws_secret_access_key,
            region=config.aws_region,
            session_token=config.aws_session_token or None,
            table_name=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            api_version=self.resolve_api_version(inputs.api_version),
        )
