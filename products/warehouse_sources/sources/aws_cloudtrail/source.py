from typing import cast

from products.warehouse_sources.sources.aws_cloudtrail._config import AwsCloudTrailSourceConfig
from products.warehouse_sources.sources.aws_cloudtrail.aws_cloudtrail import (
    AwsCloudTrailResumeConfig,
    aws_cloudtrail_source,
    validate_credentials,
)
from products.warehouse_sources.sources.aws_cloudtrail.settings import (
    ACCESS_DENIED_CODES,
    AWS_SESSION_ACTIONS,
    CLOUDTRAIL_API_VERSION,
    CREDENTIAL_ERRORS,
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
class AwsCloudTrailSource(ResumableSource[AwsCloudTrailSourceConfig, AwsCloudTrailResumeConfig]):
    codebase_detection = detect(
        env=("^(AWS_CLOUD_TRAIL|AWSCLOUDTRAIL)_",),
        npm=("@aws-sdk/client-cloudtrail",),
        cargo=("aws-sdk-cloudtrail", "aws-sdk-cloudtraildata"),
        go=("github.com/aws/aws-sdk-go-v2/service/cloudtrail",),
        maven=(
            "software.amazon.awssdk:cloudtrail",
            "com.amazonaws:aws-java-sdk-cloudtrail",
            "com.amazonaws:aws-cloudtrail-processing-library",
            "com.amazonaws:aws-java-sdk-cloudtraildata",
            "software.amazon.awssdk:cloudtraildata",
        ),
        rubygems=("aws-sdk-cloudtrail",),
    )

    lists_tables_without_credentials = True
    supported_versions = (CLOUDTRAIL_API_VERSION,)
    default_version = CLOUDTRAIL_API_VERSION
    api_docs_url = "https://docs.aws.amazon.com/awscloudtrail/latest/APIReference/Welcome.html"

    flat_stored_selects = AWS_FLAT_STORED_SELECTS
    aws_session_actions = AWS_SESSION_ACTIONS
    credential_kind = "aws-cloud-trail"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSCLOUDTRAIL

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        errors: dict[str, str | None] = {
            **AWS_AUTH_NON_RETRYABLE_ERRORS,
            **{f"AWS CloudTrail request failed: {code}": message for code, message in CREDENTIAL_ERRORS.items()},
        }
        errors.update(
            {
                f"AWS CloudTrail request failed: {code}": "Grant the CloudTrail permissions listed in the source setup for the tables you select."
                for code in ACCESS_DENIED_CODES
            }
        )
        return errors

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.aws_cloudtrail.canonical_descriptions import CANONICAL_DESCRIPTIONS

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
        try:
            credentials = resolve_aws_credentials(config.aws_auth, team_id, AWS_SESSION_ACTIONS)
        except AwsAuthError as error:
            return False, str(error)
        return validate_credentials(
            credentials,
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
            credentials=resolve_aws_credentials(config.aws_auth, inputs.team_id, AWS_SESSION_ACTIONS),
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
Insights tables also need `cloudtrail:ListInsightsData`.
The Lake queries table also needs `cloudtrail:ListQueries` and `cloudtrail:DescribeQuery`.
Connect with an IAM role, or enter an access key ID and secret access key. Add a session token for temporary credentials.

Event imports cover the past 90 days. They include management events and trail Insights events, but exclude data events.
Insights must be enabled on a trail to return Insights events.
The event stores table imports CloudTrail Lake settings, not stored events.
The Lake queries table imports query history from the past 7 days, not query results.
CloudTrail Lake is available only to existing customers after May 31, 2026.""",
            iconPath="/static/services/aws_cloudtrail.png",
            docsUrl="https://posthog.com/docs/cdp/sources/aws-cloudtrail",
            releaseStatus=ReleaseStatus.BETA,
            keywords=["aws", "cloudtrail", "audit", "events"],
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
