from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cloudtrail.aws_cloudtrail import (
    AwsCloudTrailResumeConfig,
    aws_cloudtrail_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cloudtrail.settings import (
    ACCESS_DENIED_CODES,
    CLOUDTRAIL_API_VERSION,
    CREDENTIAL_ERRORS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awscloudtrail import (
    AwsCloudTrailSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsCloudTrailSource(ResumableSource[AwsCloudTrailSourceConfig, AwsCloudTrailResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = (CLOUDTRAIL_API_VERSION,)
    default_version = CLOUDTRAIL_API_VERSION
    api_docs_url = "https://docs.aws.amazon.com/awscloudtrail/latest/APIReference/Welcome.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSCLOUDTRAIL

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        errors: dict[str, str | None] = {
            f"AWS CloudTrail request failed: {code}": message for code, message in CREDENTIAL_ERRORS.items()
        }
        errors.update(
            {
                f"AWS CloudTrail request failed: {code}": "Grant cloudtrail:LookupEvents, cloudtrail:DescribeTrails, or cloudtrail:ListEventDataStores for the tables you select."
                for code in ACCESS_DENIED_CODES
            }
        )
        return errors

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cloudtrail.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AwsCloudTrailSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, descriptions=ENDPOINT_DESCRIPTIONS)

    def validate_credentials(
        self,
        config: AwsCloudTrailSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(
            config.aws_access_key_id,
            config.aws_secret_access_key,
            config.aws_session_token,
            config.region,
            self.resolve_api_version(api_version),
            schema_name,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AwsCloudTrailResumeConfig]:
        return ResumableSourceManager(inputs, AwsCloudTrailResumeConfig)

    def source_for_pipeline(
        self,
        config: AwsCloudTrailSourceConfig,
        resumable_source_manager: ResumableSourceManager[AwsCloudTrailResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aws_cloudtrail_source(
            access_key_id=config.aws_access_key_id,
            secret_access_key=config.aws_secret_access_key,
            session_token=config.aws_session_token,
            region=config.region,
            api_version=self.resolve_api_version(inputs.api_version),
            endpoint_name=inputs.schema_name,
            manager=resumable_source_manager,
            last_value=inputs.db_incremental_field_last_value if inputs.should_use_incremental_field else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSCLOUDTRAIL,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="AWS CloudTrail",
            caption="""Sync CloudTrail events and settings from one AWS region.

Grant `cloudtrail:LookupEvents`, `cloudtrail:DescribeTrails`, and `cloudtrail:ListEventDataStores` for the tables you select.
Enter an access key ID and secret access key. Add a session token for temporary credentials.

Event imports cover the past 90 days. They include management events and trail Insights events, but exclude data events.
Insights must be enabled on a trail to return Insights events.
The event stores table imports CloudTrail Lake settings, not stored events.
CloudTrail Lake is available only to existing customers after May 31, 2026.""",
            iconPath="/static/services/aws_cloudtrail.png",
            docsUrl="https://posthog.com/docs/cdp/sources/aws-cloudtrail",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["aws", "cloudtrail", "audit", "events"],
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
                        secret=True,
                        caption="Temporary credentials expire. Update them before scheduled imports run.",
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
