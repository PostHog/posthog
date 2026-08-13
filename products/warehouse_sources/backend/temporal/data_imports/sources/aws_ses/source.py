from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_ses.aws_ses import (
    AwsSesResumeConfig,
    aws_ses_source,
    probe_endpoint_permissions,
    validate_credentials as validate_aws_ses_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_ses.settings import (
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsses import AwsSesSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsSesSource(ResumableSource[AwsSesSourceConfig, AwsSesResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://docs.aws.amazon.com/ses/latest/APIReference-V2/Welcome.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSSES

    @property
    def connection_host_fields(self) -> list[str]:
        # The region picks the endpoint the signed request, and so the customer's key, is sent to.
        return ["aws_region"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "Amazon SES request failed: UnrecognizedClientException": "AWS rejected the access key. Please check the access key ID and secret access key, and that the key is still active.",
            "Amazon SES request failed: InvalidClientTokenId": "AWS rejected the access key. Please check the access key ID and secret access key, and that the key is still active.",
            "Amazon SES request failed: SignatureDoesNotMatch": "AWS rejected the request signature. Please re-enter the secret access key.",
            "Amazon SES request failed: InvalidSignatureException": "AWS rejected the request signature. If you are using temporary credentials, the session token has expired.",
            "Amazon SES request failed: ExpiredTokenException": "The AWS session token has expired. Please reconnect with fresh credentials.",
            "Amazon SES request failed: AccessDeniedException": "These AWS credentials are missing SES read permissions. Grant ses:GetAccount, ses:ListConfigurationSets, ses:GetConfigurationSet, ses:ListEmailIdentities, ses:GetEmailIdentity and ses:ListSuppressedDestinations to the IAM user or role.",
            "Invalid AWS region": "Enter a valid AWS region code like us-east-1.",
            "AWS access key ID and secret access key are required": "Enter both an AWS access key ID and a secret access key.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.aws_ses.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AwsSesSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, descriptions=ENDPOINT_DESCRIPTIONS)

    def validate_credentials(
        self,
        config: AwsSesSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_aws_ses_credentials(
            config.aws_access_key_id,
            config.aws_secret_access_key,
            config.aws_session_token,
            config.aws_region,
            schema_name=schema_name,
        )

    def get_endpoint_permissions(
        self, config: AwsSesSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        return probe_endpoint_permissions(
            config.aws_access_key_id,
            config.aws_secret_access_key,
            config.aws_session_token,
            config.aws_region,
            endpoints,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AwsSesResumeConfig]:
        return ResumableSourceManager[AwsSesResumeConfig](inputs, AwsSesResumeConfig)

    def source_for_pipeline(
        self,
        config: AwsSesSourceConfig,
        resumable_source_manager: ResumableSourceManager[AwsSesResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aws_ses_source(
            aws_access_key_id=config.aws_access_key_id,
            aws_secret_access_key=config.aws_secret_access_key,
            aws_session_token=config.aws_session_token,
            aws_region=config.aws_region,
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
            name=SchemaExternalDataSourceType.AWS_SES,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Amazon SES",
            caption="""Sync your Amazon SES account data into the PostHog Data warehouse.

Create an IAM user or role with the `ses:GetAccount`, `ses:ListConfigurationSets`, `ses:GetConfigurationSet`, `ses:ListEmailIdentities`, `ses:GetEmailIdentity` and `ses:ListSuppressedDestinations` permissions, then paste its access key ID and secret access key. Add a session token too if you are using temporary credentials.

SES data is regional, so connect one source per AWS Region you send email from. This source syncs account-level data. Per-message send, bounce, and complaint events are only available through SES event destinations, not the SES API.""",
            iconPath="/static/services/aws_ses.png",
            docsUrl="https://posthog.com/docs/cdp/sources/aws-ses",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["aws", "ses", "simple email service", "email"],
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
