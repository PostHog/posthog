from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs
    api_docs_url = "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_Operations_AWS_Cost_Explorer_Service.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSCOSTANOMALYDETECTION

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "AWS Cost Anomaly Detection request failed: UnrecognizedClientException": "AWS rejected the access key. Please check the access key ID and secret access key, and that the key is still active.",
            "AWS Cost Anomaly Detection request failed: InvalidClientTokenId": "AWS rejected the access key. Please check the access key ID and secret access key, and that the key is still active.",
            "AWS Cost Anomaly Detection request failed: SignatureDoesNotMatch": "AWS rejected the request signature. Please re-enter the secret access key.",
            "AWS Cost Anomaly Detection request failed: InvalidSignatureException": "AWS rejected the request signature. If you are using temporary credentials, the session token has expired.",
            "AWS Cost Anomaly Detection request failed: ExpiredTokenException": "The AWS session token has expired. Please reconnect with fresh credentials.",
            "AWS Cost Anomaly Detection request failed: AccessDeniedException": "These AWS credentials are missing Cost Explorer permissions. Grant ce:GetAnomalies, ce:GetAnomalyMonitors and ce:GetAnomalySubscriptions to the IAM user or role.",
            "AWS Cost Anomaly Detection request failed: DataUnavailableException": "AWS has no Cost Explorer data for this account yet. Enable Cost Explorer in the AWS console, then try again in up to 24 hours once AWS has prepared the data.",
            "AWS access key ID and secret access key are required": "Enter both an AWS access key ID and a secret access key.",
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
        return validate_aws_cost_anomaly_detection_credentials(
            config.aws_access_key_id,
            config.aws_secret_access_key,
            config.aws_session_token,
            schema_name=schema_name,
        )

    def get_endpoint_permissions(
        self,
        config: AwsCostAnomalyDetectionSourceConfig,
        team_id: int,
        endpoints: list[str],
        api_version: str | None = None,
    ) -> dict[str, str | None]:
        return probe_endpoint_permissions(
            config.aws_access_key_id,
            config.aws_secret_access_key,
            config.aws_session_token,
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
            aws_access_key_id=config.aws_access_key_id,
            aws_secret_access_key=config.aws_secret_access_key,
            aws_session_token=config.aws_session_token,
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
            name=SchemaExternalDataSourceType.AWS_COST_ANOMALY_DETECTION,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="AWS Cost Anomaly Detection",
            caption="""Sync the cost anomalies AWS detected on your account into the PostHog Data warehouse.

Create an IAM user or role with the `ce:GetAnomalies`, `ce:GetAnomalyMonitors` and `ce:GetAnomalySubscriptions` permissions, then paste its access key ID and secret access key. Add a session token too if you are using temporary credentials.

Cost Explorer has to be enabled once in the AWS console, and it can take up to 24 hours before data is ready. AWS keeps anomalies for 90 days, so that is as far back as a first sync reaches. You only see the monitors and subscriptions created by the account you connect, so connect the management (payer) account for organization-wide coverage.""",
            iconPath="/static/services/aws_cost_anomaly_detection.png",
            docsUrl="https://posthog.com/docs/cdp/sources/aws-cost-anomaly-detection",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["aws", "finops", "cloud spend", "cost explorer", "cost anomaly detection"],
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
                        placeholder="Only needed for temporary credentials",
                        caption="Only for temporary credentials. Session tokens expire after a few hours, so scheduled syncs will fail once the token expires. Use a permanent access key (starts with AKIA) for recurring imports.",
                        secret=True,
                    ),
                ],
            ),
        )
