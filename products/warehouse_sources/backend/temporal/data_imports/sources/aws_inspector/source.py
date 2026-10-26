from typing import cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_inspector.aws_inspector import (
    AwsInspectorResumeConfig,
    aws_inspector_source,
    validate_credentials as validate_aws_inspector_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_inspector.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_inspector.settings import (
    DEFAULT_REGION,
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    ERROR_MESSAGES,
    INCREMENTAL_FIELDS,
    INSPECTOR_API_VERSION,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.aws_auth import (
    AWS_AUTH_NON_RETRYABLE_ERRORS,
    AwsAuthError,
    aws_auth_field,
    resolve_aws_credentials,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsinspector import (
    AwsInspectorSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsInspectorSource(ResumableSource[AwsInspectorSourceConfig, AwsInspectorResumeConfig]):
    codebase_detection = detect(
        env=("^(AWS_INSPECTOR|AWSINSPECTOR)_",),
        npm=("@aws-sdk/client-inspector2", "@aws-sdk/client-inspector"),
        cargo=("aws-sdk-inspector2", "aws-sdk-inspector"),
        go=("github.com/aws/aws-sdk-go-v2/service/inspector2", "github.com/aws/aws-sdk-go-v2/service/inspector"),
        maven=(
            "software.amazon.awssdk:inspector2",
            "software.amazon.awssdk:inspector",
            "com.amazonaws:aws-java-sdk-inspector2",
            "com.amazonaws:aws-java-sdk-inspector",
            "com.amazonaws:aws-java-sdk-inspectorscan",
            "software.amazon.awssdk:inspectorscan",
        ),
        rubygems=("aws-sdk-inspector2", "aws-sdk-inspector"),
    )

    lists_tables_without_credentials = True
    supported_versions = (INSPECTOR_API_VERSION,)
    default_version = INSPECTOR_API_VERSION
    api_docs_url = "https://docs.aws.amazon.com/inspector/v2/APIReference/Welcome.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSINSPECTOR

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            **AWS_AUTH_NON_RETRYABLE_ERRORS,
            **{f"AWS Inspector request failed: {code}": message for code, message in ERROR_MESSAGES.items()},
        }

    def get_retryable_errors(self) -> set[str]:
        return {
            "AWS Inspector request failed: ThrottlingException",
            "AWS Inspector request failed: InternalServerException",
            "AWS Inspector request failed: HTTP 429",
            "AWS Inspector request failed: HTTP 5",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AwsInspectorSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, descriptions=ENDPOINT_DESCRIPTIONS)

    def validate_credentials(
        self,
        config: AwsInspectorSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            credentials = resolve_aws_credentials(config.aws_auth, team_id)
        except AwsAuthError as error:
            return False, str(error)
        return validate_aws_inspector_credentials(
            config, credentials, schema_name, self.resolve_api_version(api_version)
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AwsInspectorResumeConfig]:
        return ResumableSourceManager(inputs, AwsInspectorResumeConfig)

    def source_for_pipeline(
        self,
        config: AwsInspectorSourceConfig,
        resumable_source_manager: ResumableSourceManager[AwsInspectorResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aws_inspector_source(
            config=config,
            credentials=resolve_aws_credentials(config.aws_auth, inputs.team_id),
            endpoint=inputs.schema_name,
            manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            last_value=inputs.db_incremental_field_last_value,
            api_version=self.resolve_api_version(inputs.api_version),
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSINSPECTOR,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="AWS Inspector",
            caption="""Sync Amazon Inspector findings, scan coverage, and CIS scans into the PostHog Data warehouse.

Enable Amazon Inspector in the region you select. Grant these IAM permissions for the tables you select:

- `findings`: `inspector2:ListFindings`
- `coverage`: `inspector2:ListCoverage`
- `coverage_statistics`: `inspector2:ListCoverageStatistics`
- `members`: `inspector2:ListMembers` (delegated administrator account only)
- `cis_scans`: `inspector2:ListCisScans`
- `cis_scan_result_details`: `inspector2:ListCisScans`, `inspector2:ListCisScanResultsAggregatedByTargetResource`, and `inspector2:GetCisScanResultDetails`
- `clusters_for_image`: `inspector2:ListCoverage` and `inspector2:GetClustersForImage`

Connect with an IAM role, or enter your access key ID and secret access key. Add a session token if you use temporary credentials.
This source reads one AWS region.""",
            iconPath="/static/services/aws_inspector.png",
            docsUrl="https://posthog.com/docs/cdp/sources/aws-inspector",
            releaseStatus=ReleaseStatus.BETA,
            keywords=["aws", "inspector", "security", "vulnerabilities"],
            fields=cast(
                list[FieldType],
                [
                    aws_auth_field(),
                    SourceFieldInputConfig(
                        name="region",
                        label="AWS region",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder=DEFAULT_REGION,
                        secret=False,
                    ),
                ],
            ),
        )
