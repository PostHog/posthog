from typing import cast

from products.warehouse_sources.sources.aws_end_user_messaging._config import AwsEndUserMessagingSourceConfig
from products.warehouse_sources.sources.aws_end_user_messaging.aws_end_user_messaging import (
    AwsEndUserMessagingResumeConfig,
    aws_end_user_messaging_source,
    validate_credentials,
)
from products.warehouse_sources.sources.aws_end_user_messaging.settings import (
    API_DOCS_URL,
    API_VERSION,
    ENDPOINTS,
    ERROR_MESSAGES,
    ERROR_PREFIX,
)
from products.warehouse_sources.sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceKey,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
    detect,
    source_key,
)

SOURCE_KEY = "AwsEndUserMessaging"


@SourceRegistry.register
class AwsEndUserMessagingSource(ResumableSource[AwsEndUserMessagingSourceConfig, AwsEndUserMessagingResumeConfig]):
    codebase_detection = detect(
        npm=("@aws-sdk/client-pinpoint-sms-voice-v2",),
        cargo=("aws-sdk-pinpointsmsvoicev2",),
        go=("github.com/aws/aws-sdk-go-v2/service/pinpointsmsvoicev2",),
        maven=("software.amazon.awssdk:pinpointsmsvoicev2",),
        rubygems=("aws-sdk-pinpointsmsvoicev2",),
    )

    lists_tables_without_credentials = True
    # The SMS and Voice v2 API sends its version only in the service model, so the pin is the model version.
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {f"{ERROR_PREFIX}: {code}": message for code, message in ERROR_MESSAGES.items()}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.aws_end_user_messaging.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AwsEndUserMessagingSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS, {}, names, descriptions={name: endpoint.description for name, endpoint in ENDPOINTS.items()}
        )

    def validate_credentials(
        self,
        config: AwsEndUserMessagingSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, schema_name)

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[AwsEndUserMessagingResumeConfig]:
        return ResumableSourceManager(inputs, AwsEndUserMessagingResumeConfig)

    def source_for_pipeline(
        self,
        config: AwsEndUserMessagingSourceConfig,
        resumable_source_manager: ResumableSourceManager[AwsEndUserMessagingResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aws_end_user_messaging_source(config, inputs.schema_name, resumable_source_manager)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            keywords=["aws eum", "eum", "amazon pinpoint", "pinpoint sms", "sms voice"],
            label="AWS End User Messaging",
            caption="""Sync the SMS and voice resources of AWS End User Messaging (formerly Amazon Pinpoint SMS) from one AWS region: phone numbers, pools, sender IDs, configuration sets, opt-out lists, opted-out numbers, keywords, registrations, verified destination numbers, protect configurations, spend limits, and account attributes and limits.

Give the IAM user or role the `sms-voice:Describe*` actions, or only these for the tables you select:
`sms-voice:DescribePhoneNumbers`, `sms-voice:DescribePools`, `sms-voice:DescribeSenderIds`, `sms-voice:DescribeConfigurationSets`, `sms-voice:DescribeOptOutLists`, `sms-voice:DescribeOptedOutNumbers`, `sms-voice:DescribeKeywords`, `sms-voice:DescribeRegistrations`, `sms-voice:DescribeVerifiedDestinationNumbers`, `sms-voice:DescribeProtectConfigurations`, `sms-voice:DescribeSpendLimits`, `sms-voice:DescribeAccountAttributes`, and `sms-voice:DescribeAccountLimits`.

The API does not return sent or received messages. To analyze message events, send them from a configuration set to an event destination such as Amazon S3. All tables use full refresh because the API has no time filter.""",
            iconPath="/static/warehouse-sources/aws_end_user_messaging/icon.png",
            docsUrl="https://posthog.com/docs/cdp/sources/aws-end-user-messaging",
            releaseStatus=ReleaseStatus.BETA,
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
                        caption="Temporary credentials expire. Update them before the next scheduled sync.",
                    ),
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
