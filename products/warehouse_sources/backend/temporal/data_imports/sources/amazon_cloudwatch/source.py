from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_cloudwatch.amazon_cloudwatch import (
    INVALID_METRIC_QUERIES,
    INVALID_REQUEST_ERROR_CODES,
    INVALID_START_DATE,
    METRIC_QUERY_FORBIDDEN,
    METRIC_QUERY_INTERNAL_ERROR,
    METRIC_QUERY_PARTIAL_DATA,
    THROTTLING_ERROR_CODES,
    VALIDATION_ERROR_MESSAGES,
    AmazonCloudWatchResumeConfig,
    amazon_cloudwatch_source,
    validate_credentials as validate_amazon_cloudwatch_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_cloudwatch.settings import (
    AMAZON_CLOUDWATCH_ENDPOINTS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.amazoncloudwatch import (
    AmazonCloudWatchSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AmazonCloudWatchSource(ResumableSource[AmazonCloudWatchSourceConfig, AmazonCloudWatchResumeConfig]):
    codebase_detection = detect(
        env=("^(AMAZON_CLOUDWATCH|CLOUDWATCH)_",),
        npm=("@aws-sdk/client-cloudwatch", "@aws-sdk/client-cloudwatch-logs"),
        cargo=("aws-sdk-cloudwatch", "aws-sdk-cloudwatchlogs"),
        go=(
            "github.com/aws/aws-sdk-go-v2/service/cloudwatch",
            "github.com/aws/aws-sdk-go-v2/service/cloudwatchlogs",
        ),
        maven=("software.amazon.awssdk:cloudwatch", "software.amazon.awssdk:cloudwatchlogs"),
        rubygems=("aws-sdk-cloudwatch", "aws-sdk-cloudwatchlogs"),
    )

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/Welcome.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AMAZONCLOUDWATCH

    @property
    def connection_host_fields(self) -> list[str]:
        # The region picks the endpoint the signed requests, and so the stored key, are sent to.
        return ["aws_region"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        errors: dict[str, str | None] = {
            f"Amazon CloudWatch request failed: {code}": message for code, message in VALIDATION_ERROR_MESSAGES.items()
        }
        errors["Amazon CloudWatch request failed: ResourceNotFoundException"] = (
            "A log group was not found in this region. Check the log group names on the source."
        )
        errors[INVALID_METRIC_QUERIES] = "The metric queries on the source are not valid. Fix them and retry the sync."
        errors[INVALID_START_DATE] = (
            "The start date on the source is not a date. Enter it as YYYY-MM-DD and retry the sync."
        )
        errors[f"Amazon CloudWatch request failed: {METRIC_QUERY_PARTIAL_DATA}"] = (
            "A metric query returns more datapoints than CloudWatch sends in one response. Use a longer period, "
            "or fewer metrics in the expression, then retry the sync."
        )
        for code in INVALID_REQUEST_ERROR_CODES:
            errors[f"Amazon CloudWatch request failed: {code}"] = (
                "AWS rejected a request built from the source settings, usually a metric query. "
                "Check the metric queries and log group names, then retry the sync."
            )
        errors[f"Amazon CloudWatch request failed: {METRIC_QUERY_FORBIDDEN}"] = (
            "These AWS credentials cannot read one of the configured metrics. Grant cloudwatch:GetMetricData "
            "for it, or remove the query from the source."
        )
        return errors

    def get_retryable_errors(self) -> set[str]:
        # `send_operation` already exhausts the transport retry and a bounded throttling retry
        # before these reach here; Temporal retries the whole activity next.
        return {f"Amazon CloudWatch request failed: {code}" for code in THROTTLING_ERROR_CODES} | {
            "Amazon CloudWatch request failed: InternalFailure",
            "Amazon CloudWatch request failed: ServiceUnavailable",
            "Amazon CloudWatch request failed: HTTP 5",
            f"Amazon CloudWatch request failed: {METRIC_QUERY_INTERNAL_ERROR}",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_cloudwatch.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AmazonCloudWatchSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            descriptions=ENDPOINT_DESCRIPTIONS,
            default_incremental_lookback_seconds={
                name: config.incremental_lookback_seconds
                for name, config in AMAZON_CLOUDWATCH_ENDPOINTS.items()
                if config.incremental_lookback_seconds is not None
            },
        )

    def validate_credentials(
        self,
        config: AmazonCloudWatchSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_amazon_cloudwatch_credentials(
            config.aws_access_key_id,
            config.aws_secret_access_key,
            config.aws_session_token,
            config.aws_region,
            config.metric_queries,
            config.start_date,
        )

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[AmazonCloudWatchResumeConfig]:
        return ResumableSourceManager[AmazonCloudWatchResumeConfig](inputs, AmazonCloudWatchResumeConfig)

    def source_for_pipeline(
        self,
        config: AmazonCloudWatchSourceConfig,
        resumable_source_manager: ResumableSourceManager[AmazonCloudWatchResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return amazon_cloudwatch_source(
            aws_access_key_id=config.aws_access_key_id,
            aws_secret_access_key=config.aws_secret_access_key,
            aws_session_token=config.aws_session_token,
            aws_region=config.aws_region,
            log_group_names=config.log_group_names,
            metric_queries=config.metric_queries,
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
            name=ExternalDataSourceType.AMAZONCLOUDWATCH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Amazon CloudWatch",
            caption="""Sync CloudWatch log events, alarms, alarm history and metric datapoints from one AWS region into the PostHog Data warehouse.

Create an IAM user or role with the `logs:DescribeLogGroups`, `logs:FilterLogEvents`, `cloudwatch:DescribeAlarms`, `cloudwatch:DescribeAlarmHistory` and `cloudwatch:GetMetricData` permissions, then paste its access key ID and secret access key. Add a session token too if you are using temporary credentials.

Log events sync from the log groups you list, or from every log group in the region (up to 50) when the list is empty. A log group or metric query added later syncs from the next sync on; resync the table to backfill its history. Any log delivered to CloudWatch Logs works, including Bedrock model invocation logs and CloudFront standard logs. Metric datapoints sync for the metric queries you configure as JSON, for example `[{"id": "cpu", "namespace": "AWS/EC2", "metric_name": "CPUUtilization", "dimensions": {"InstanceId": "i-0123456789abcdef0"}, "stat": "Average", "period": 300}]`. S3 Storage Lens metrics live in the `AWS/S3/Storage-Lens` namespace. Older datapoints come back at the resolution CloudWatch keeps for them: 5 minutes after 15 days and 1 hour after 63 days.""",
            iconPath="/static/services/amazon_cloudwatch.png",
            docsUrl="https://posthog.com/docs/cdp/sources/amazon-cloudwatch",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["aws", "cloudwatch", "logs", "metrics", "alarms"],
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
                        name="log_group_names",
                        label="Log groups to sync (one per line, empty syncs every log group)",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=False,
                        placeholder="/aws/lambda/my-function",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="metric_queries",
                        label="Metric queries (JSON list)",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=False,
                        placeholder='[{"id": "cpu", "namespace": "AWS/EC2", "metric_name": "CPUUtilization", "stat": "Average", "period": 300}]',
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date (defaults to 7 days back for logs, 14 for metrics, 30 for alarm history)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="2024-01-01",
                        secret=False,
                    ),
                ],
            ),
        )
