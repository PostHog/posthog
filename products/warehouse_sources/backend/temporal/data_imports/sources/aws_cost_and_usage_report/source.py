from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_and_usage_report.aws_cost_and_usage_report import (
    DELIVERY_IN_PROGRESS,
    ERROR_PREFIX,
    MANIFEST_UNREADABLE,
    UNSUPPORTED_COMPRESSION,
    VALIDATION_ERROR_MESSAGES,
    WRONG_REGION_CODES,
    WRONG_REGION_MESSAGE,
    CostAndUsageReportResumeConfig,
    aws_cost_and_usage_report_source,
    validate_credentials as validate_cost_and_usage_report_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_and_usage_report.settings import (
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awscostandusagereport import (
    AwsCostAndUsageReportSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsCostAndUsageReportSource(ResumableSource[AwsCostAndUsageReportSourceConfig, CostAndUsageReportResumeConfig]):
    codebase_detection = detect(
        npm=("@aws-sdk/client-bcm-data-exports", "@aws-sdk/client-cost-and-usage-report-service"),
        cargo=("aws-sdk-bcmdataexports", "aws-sdk-costandusagereport"),
        go=(
            "github.com/aws/aws-sdk-go-v2/service/bcmdataexports",
            "github.com/aws/aws-sdk-go-v2/service/costandusagereportservice",
        ),
        maven=("software.amazon.awssdk:bcmdataexports", "software.amazon.awssdk:costandusagereport"),
        rubygems=("aws-sdk-bcmdataexports", "aws-sdk-costandusagereportservice"),
    )

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.aws.amazon.com/cur/latest/userguide/dataexports-export-delivery.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSCOSTANDUSAGEREPORT

    @property
    def connection_host_fields(self) -> list[str]:
        # The region and bucket decide where the signed requests, and so the stored key, are sent.
        return ["aws_region", "bucket"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        errors: dict[str, str | None] = {
            f"{ERROR_PREFIX}: {code}": message for code, message in VALIDATION_ERROR_MESSAGES.items()
        }
        errors.update({f"{ERROR_PREFIX}: {code}": WRONG_REGION_MESSAGE for code in WRONG_REGION_CODES})
        errors["Enter the first billing period as YYYY-MM"] = (
            "The first billing period on the source is not in YYYY-MM form. Fix it and retry the sync."
        )
        errors[f"{ERROR_PREFIX}: {UNSUPPORTED_COMPRESSION}"] = (
            "A file in the export uses Brotli compression, which PostHog can't read. "
            "Check that only AWS writes to the export's S3 prefix, then retry the sync."
        )
        return errors

    def get_retryable_errors(self) -> set[str]:
        # An "overwrite" export is being rewritten; the next attempt reads the finished delivery.
        # An unreadable manifest is replaced by the next delivery.
        return {f"{ERROR_PREFIX}: {DELIVERY_IN_PROGRESS}", f"{ERROR_PREFIX}: {MANIFEST_UNREADABLE}"}

    def resume_covers_run(self, *, incremental_or_append: bool, schema_name: str | None = None) -> bool:
        return not incremental_or_append

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[CostAndUsageReportResumeConfig]:
        return ResumableSourceManager[CostAndUsageReportResumeConfig](inputs, CostAndUsageReportResumeConfig)

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_and_usage_report.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AwsCostAndUsageReportSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, descriptions=ENDPOINT_DESCRIPTIONS)

    def validate_credentials(
        self,
        config: AwsCostAndUsageReportSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_cost_and_usage_report_credentials(
            config.aws_access_key_id,
            config.aws_secret_access_key,
            config.aws_session_token,
            config.aws_region,
            config.bucket,
            config.prefix,
            config.export_name,
            config.first_billing_period,
        )

    def source_for_pipeline(
        self,
        config: AwsCostAndUsageReportSourceConfig,
        resumable_source_manager: ResumableSourceManager[CostAndUsageReportResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in ENDPOINTS:
            raise ValueError(f"Unknown AWS Cost and Usage Report table: {inputs.schema_name}")
        # A reset's first attempt reads from the start. Later attempts of the run keep its progress.
        if inputs.reset_pipeline and inputs.activity_attempt == 1:
            resumable_source_manager.clear_state()
        return aws_cost_and_usage_report_source(
            aws_access_key_id=config.aws_access_key_id,
            aws_secret_access_key=config.aws_secret_access_key,
            aws_session_token=config.aws_session_token,
            aws_region=config.aws_region,
            bucket=config.bucket,
            prefix=config.prefix,
            export_name=config.export_name,
            first_billing_period=config.first_billing_period,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSCOSTANDUSAGEREPORT,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="AWS Cost and Usage Report",
            caption="""Sync the line items of an AWS Data Exports export (Cost and Usage Report 2.0 or FOCUS) from its S3 bucket into the PostHog Data warehouse.

Create the export in the AWS Billing console under **Data Exports**, delivered to S3 as Parquet or gzip CSV. Parquet keeps the column types of the export; gzip CSV takes them from the export's manifest. Then create an IAM user or role with `s3:ListBucket` on the bucket and `s3:GetObject` on the export's prefix, and paste its access key ID and secret access key.

AWS rewrites a whole billing period on each delivery and restates the previous month for up to two weeks after it ends, so every sync rebuilds the table from the latest delivery of each billing period. Each sync reads every month from the first billing period on, and each read counts as synced rows, so start at the earliest month you need.""",
            iconPath="/static/services/aws_cost_and_usage_report.png",
            docsUrl="https://posthog.com/docs/cdp/sources/aws-cost-and-usage-report",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["aws", "cur", "finops", "cloud spend", "data exports", "focus"],
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
                        label="Bucket region",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="us-east-1",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="bucket",
                        label="S3 bucket",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-billing-exports",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="prefix",
                        label="S3 path prefix (as set on the export, empty when none)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="billing/cur",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="export_name",
                        label="Export name",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-cur-export",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="first_billing_period",
                        label="First billing period to sync (YYYY-MM)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="2024-01",
                        secret=False,
                    ),
                ],
            ),
        )
