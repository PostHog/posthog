from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_organizations.aws_organizations import (
    AwsOrganizationsResumeConfig,
    aws_organizations_source,
    probe_endpoint_permissions,
    validate_credentials as validate_aws_organizations_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_organizations.settings import (
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    ORGANIZATIONS_API_VERSION,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsorganizations import (
    AwsOrganizationsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_MANAGEMENT_ACCOUNT_HINT = (
    "Organizations list operations only work from the management account or a delegated administrator."
)


@SourceRegistry.register
class AwsOrganizationsSource(ResumableSource[AwsOrganizationsSourceConfig, AwsOrganizationsResumeConfig]):
    codebase_detection = detect(
        env=("^(AWS_ORGANIZATIONS|AWSORGANIZATIONS)_",),
        npm=("@aws-sdk/client-organizations",),
        cargo=("aws-sdk-organizations",),
        go=("github.com/aws/aws-sdk-go-v2/service/organizations",),
        maven=("software.amazon.awssdk:organizations", "com.amazonaws:aws-java-sdk-organizations"),
        rubygems=("aws-sdk-organizations",),
    )

    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs
    supported_versions = (ORGANIZATIONS_API_VERSION,)
    default_version = ORGANIZATIONS_API_VERSION
    api_docs_url = "https://docs.aws.amazon.com/organizations/latest/APIReference/API_Operations.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSORGANIZATIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            **AWS_AUTH_NON_RETRYABLE_ERRORS,
            "AWS Organizations request failed: UnrecognizedClientException": "AWS rejected the access key. Please check the access key ID and secret access key, and that the key is still active.",
            "AWS Organizations request failed: InvalidClientTokenId": "AWS rejected the access key. Please check the access key ID and secret access key, and that the key is still active.",
            "AWS Organizations request failed: SignatureDoesNotMatch": "AWS rejected the request signature. Please re-enter the secret access key.",
            "AWS Organizations request failed: InvalidSignatureException": "AWS rejected the request signature. If you are using temporary credentials, the session token has expired.",
            "AWS Organizations request failed: ExpiredTokenException": "The AWS session token has expired. Please reconnect with fresh credentials.",
            "AWS Organizations request failed: AccessDeniedException": f"These AWS credentials are missing AWS Organizations read permissions. Grant organizations:DescribeOrganization, organizations:ListAccounts, organizations:ListParents, organizations:ListRoots, organizations:ListOrganizationalUnitsForParent, organizations:ListPolicies, organizations:ListTargetsForPolicy, organizations:ListTagsForResource, organizations:ListDelegatedAdministrators and organizations:ListDelegatedServicesForAccount to the IAM user or role. {_MANAGEMENT_ACCOUNT_HINT}",
            "AWS Organizations request failed: AWSOrganizationsNotInUseException": "This AWS account isn't a member of an organization. Connect a key from an account in an AWS organization.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.aws_organizations.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AwsOrganizationsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, descriptions=ENDPOINT_DESCRIPTIONS)

    def validate_credentials(
        self,
        config: AwsOrganizationsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            credentials = resolve_aws_credentials(config.aws_auth, team_id)
        except AwsAuthError as error:
            return False, str(error)
        return validate_aws_organizations_credentials(
            credentials,
            schema_name=schema_name,
            api_version=self.resolve_api_version(api_version),
        )

    def get_endpoint_permissions(
        self,
        config: AwsOrganizationsSourceConfig,
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
            api_version=self.resolve_api_version(api_version),
        )

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[AwsOrganizationsResumeConfig]:
        return ResumableSourceManager[AwsOrganizationsResumeConfig](inputs, AwsOrganizationsResumeConfig)

    def source_for_pipeline(
        self,
        config: AwsOrganizationsSourceConfig,
        resumable_source_manager: ResumableSourceManager[AwsOrganizationsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aws_organizations_source(
            credentials=resolve_aws_credentials(config.aws_auth, inputs.team_id),
            endpoint=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
            logger=inputs.logger,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSORGANIZATIONS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="AWS Organizations",
            caption="""Sync your AWS organization structure into the PostHog Data warehouse, so cost and usage data can be read by account name, organizational unit, and tag.

Create an IAM user or role with the `organizations:DescribeOrganization`, `organizations:ListAccounts`, `organizations:ListParents`, `organizations:ListRoots`, `organizations:ListOrganizationalUnitsForParent`, `organizations:ListPolicies`, `organizations:ListTargetsForPolicy`, `organizations:ListTagsForResource`, `organizations:ListDelegatedAdministrators` and `organizations:ListDelegatedServicesForAccount` permissions. Connect with the IAM role, or paste an access key ID and secret access key. Add a session token too if you are using temporary credentials.

Use a key from the management account or from a member account that is a delegated administrator. Keys from other member accounts can only read the organization table.

AWS Organizations is a global service, so there is nothing to pick a region for. This source syncs the accounts, organizational units, and policies in the standard AWS partition.""",
            iconPath="/static/services/aws_organizations.png",
            docsUrl="https://posthog.com/docs/cdp/sources/aws-organizations",
            releaseStatus=ReleaseStatus.BETA,
            keywords=["aws", "organizations", "accounts", "organizational units"],
            fields=cast(
                list[FieldType],
                [
                    aws_auth_field(),
                ],
            ),
        )
