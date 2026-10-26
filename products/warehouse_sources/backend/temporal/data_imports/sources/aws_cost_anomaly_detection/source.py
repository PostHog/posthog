from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_anomaly_detection.aws_cost_anomaly_detection import (
    AwsCostAnomalyDetectionResumeConfig,
    aws_cost_anomaly_detection_source,
    probe_endpoint_permissions,
    validate_credentials as validate_aws_cost_anomaly_detection_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_anomaly_detection.settings import (
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awscostanomalydetection import (
    AwsCostAnomalyDetectionSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsCostAnomalyDetectionSource(
    ResumableSource[AwsCostAnomalyDetectionSourceConfig, AwsCostAnomalyDetectionResumeConfig]
):
    codebase_detection = detect(
        env=("^(AWS_COST_ANOMALY_DETECTION|AWSCOSTANOMALYDETECTION)_",),
        npm=("@aws-sdk/client-cost-explorer",),
        cargo=("aws-sdk-costexplorer",),
        go=("github.com/aws/aws-sdk-go-v2/service/costexplorer",),
        maven=("software.amazon.awssdk:costexplorer", "com.amazonaws:aws-java-sdk-costexplorer"),
        rubygems=("aws-sdk-costexplorer",),
    )

    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs
    api_docs_url = "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_Operations_AWS_Cost_Explorer_Service.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSCOSTANOMALYDETECTION

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            **AWS_AUTH_NON_RETRYABLE_ERRORS,
            "AWS Cost Anomaly Detection request failed: UnrecognizedClientException": "AWS rejected the access key. Please check the access key ID and secret access key, and that the key is still active.",
            "AWS Cost Anomaly Detection request failed: InvalidClientTokenId": "AWS rejected the access key. Please check the access key ID and secret access key, and that the key is still active.",
            "AWS Cost Anomaly Detection request failed: SignatureDoesNotMatch": "AWS rejected the request signature. Please re-enter the secret access key.",
            "AWS Cost Anomaly Detection request failed: InvalidSignatureException": "AWS rejected the request signature. If you are using temporary credentials, the session token has expired.",
            "AWS Cost Anomaly Detection request failed: ExpiredTokenException": "The AWS session token has expired. Please reconnect with fresh credentials.",
            "AWS Cost Anomaly Detection request failed: AccessDeniedException": "These AWS credentials are missing Cost Explorer permissions. Grant ce:GetAnomalies, ce:GetAnomalyMonitors and ce:GetAnomalySubscriptions to the IAM user or role.",
            "AWS Cost Anomaly Detection request failed: DataUnavailableException": "AWS has no Cost Explorer data for this account yet. Enable Cost Explorer in the AWS console, then try again in up to 24 hours once AWS has prepared the data.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_anomaly_detection.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AwsCostAnomalyDetectionSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, descriptions=ENDPOINT_DESCRIPTIONS)

    def validate_credentials(
        self,
        config: AwsCostAnomalyDetectionSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            credentials = resolve_aws_credentials(config.aws_auth, team_id)
        except AwsAuthError as error:
            return False, str(error)
        return validate_aws_cost_anomaly_detection_credentials(
            credentials,
            schema_name=schema_name,
        )

    def get_endpoint_permissions(
        self,
        config: AwsCostAnomalyDetectionSourceConfig,
        team_id: int,
        endpoints: list[str],
        api_version: str | None = None,
    ) -> dict[str, str | None]:
        try:
            credentials = resolve_aws_credentials(config.aws_auth, team_id)
        except AwsAuthError as error:
            return {endpoint: str(error) for endpoint in endpoints}
        return probe_endpoint_permissions(
            credentials,
            endpoints,
        )

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[AwsCostAnomalyDetectionResumeConfig]:
        return ResumableSourceManager[AwsCostAnomalyDetectionResumeConfig](inputs, AwsCostAnomalyDetectionResumeConfig)

    def source_for_pipeline(
        self,
        config: AwsCostAnomalyDetectionSourceConfig,
        resumable_source_manager: ResumableSourceManager[AwsCostAnomalyDetectionResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aws_cost_anomaly_detection_source(
            credentials=resolve_aws_credentials(config.aws_auth, inputs.team_id),
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
            name=ExternalDataSourceType.AWSCOSTANOMALYDETECTION,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="AWS Cost Anomaly Detection",
            caption="""Sync the cost anomalies AWS detected on your account into the PostHog Data warehouse.

Create an IAM user or role with the `ce:GetAnomalies`, `ce:GetAnomalyMonitors` and `ce:GetAnomalySubscriptions` permissions. Connect with the IAM role, or paste an access key ID and secret access key. Add a session token too if you are using temporary credentials.

Cost Explorer has to be enabled once in the AWS console, and it can take up to 24 hours before data is ready. AWS keeps anomalies for 90 days, so that is as far back as a first sync reaches. You only see the monitors and subscriptions created by the account you connect, so connect the management (payer) account for organization-wide coverage.""",
            iconPath="/static/services/aws_cost_anomaly_detection.png",
            docsUrl="https://posthog.com/docs/cdp/sources/aws-cost-anomaly-detection",
            releaseStatus=ReleaseStatus.GA,
            keywords=["aws", "finops", "cloud spend", "cost explorer", "cost anomaly detection"],
            fields=cast(
                list[FieldType],
                [
                    aws_auth_field(),
                ],
            ),
        )
