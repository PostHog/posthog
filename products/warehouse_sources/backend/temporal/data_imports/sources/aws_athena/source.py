from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_athena.athena import (
    ERROR_PREFIX,
    QUERY_ERROR_PREFIX,
    TABLE_NOT_FOUND,
    TABLE_NOT_FOUND_MESSAGE,
    THROTTLING_ERROR_CODES,
    VALIDATION_ERROR_MESSAGES,
    AthenaImplementation,
    validate_credentials as validate_athena_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.base import SQLSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsathena import (
    AwsAthenaSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_ATHENA_IMPLEMENTATION = AthenaImplementation()


@SourceRegistry.register
class AwsAthenaSource(SQLSource[AwsAthenaSourceConfig]):
    codebase_detection = detect(
        npm=("@aws-sdk/client-athena", "athena-express"),
        pypi=("pyathena", "awswrangler"),
        cargo=("aws-sdk-athena",),
        go=("github.com/aws/aws-sdk-go-v2/service/athena",),
        maven=("software.amazon.awssdk:athena", "com.amazonaws:athena-jdbc"),
        rubygems=("aws-sdk-athena",),
    )

    api_docs_url = "https://docs.aws.amazon.com/athena/latest/APIReference/Welcome.html"

    @property
    def get_implementation(self) -> AthenaImplementation:
        return _ATHENA_IMPLEMENTATION

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSATHENA

    @property
    def connection_host_fields(self) -> list[str]:
        # The region picks the endpoint the signed requests, and so the stored key, are sent to.
        return ["aws_region"]

    def validate_credentials(
        self,
        config: AwsAthenaSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_athena_credentials(config)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        errors: dict[str, str | None] = {
            **self.default_non_retryable_errors(),
            **{f"{ERROR_PREFIX}: {code}": message for code, message in VALIDATION_ERROR_MESSAGES.items()},
        }
        errors[f"{ERROR_PREFIX}: InvalidRequestException"] = (
            "Athena rejected the request. Check the workgroup, the output location and the table's columns, then retry."
        )
        errors[f"{ERROR_PREFIX}: {TABLE_NOT_FOUND}"] = TABLE_NOT_FOUND_MESSAGE
        errors[f"{QUERY_ERROR_PREFIX}: USER_ERROR"] = (
            "Athena could not run the query for this table. A column may have been renamed or dropped, or the "
            "credentials cannot read the table's S3 data. Fix that, then retry the sync."
        )
        return errors

    def get_retryable_errors(self) -> set[str]:
        return {f"{ERROR_PREFIX}: {code}" for code in THROTTLING_ERROR_CODES} | {
            f"{ERROR_PREFIX}: HTTP 5",
            f"{ERROR_PREFIX}: InternalServerException",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSATHENA,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Amazon Athena",
            caption="""Sync tables from an AWS Glue database through Amazon Athena into the PostHog Data warehouse.

Create an IAM user or role with `glue:GetDatabase`, `glue:GetTables`, `glue:GetTable`, `glue:GetPartitions`, `glue:GetPartition`, `glue:BatchGetPartition`, `athena:GetWorkGroup`, `athena:StartQueryExecution`, `athena:GetQueryExecution`, `athena:GetQueryResults` and `athena:StopQueryExecution`, plus read access to the tables' S3 data and read and write access to the query result location. Paste its access key ID and secret access key.

Each sync runs one Athena query per table, which Athena bills by the data it scans. An incremental sync filters on the chosen column, so a partitioned table keyed on that column scans less.""",
            iconPath="/static/services/aws_athena.png",
            docsUrl="https://posthog.com/docs/cdp/sources/aws-athena",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["aws", "athena", "glue", "presto", "trino", "sql"],
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
                        name="aws_region",
                        label="AWS region",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="us-east-1",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="database",
                        label="Glue database",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="analytics",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="workgroup",
                        label="Athena workgroup (defaults to primary)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="primary",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="output_location",
                        label="S3 output location (only when the workgroup has none)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="s3://my-athena-results/posthog/",
                        secret=False,
                    ),
                ],
            ),
        )
