import dataclasses
from typing import Any, cast

from products.warehouse_sources.sources.amazon_s3._config import AmazonS3AwsAuthConfig, AmazonS3SourceConfig
from products.warehouse_sources.sources.sdk import (
    AWS_AUTH_NON_RETRYABLE_ERRORS,
    AWS_FLAT_STORED_SELECTS,
    FEATURE_FLAG,
    KEYWORDS,
    S3_EXAMPLE_URL,
    AwsAuthError,
    DataWarehouseSourceCategory,
    DiscoveryOptions,
    ExternalDataSourceType,
    FieldType,
    ObjectStorageError,
    ObjectStorageSource,
    ObjectStoreConfig,
    ObjectStoreProvider,
    ReleaseStatus,
    RoleCredentials,
    SelfManagedCredential,
    SelfManagedLocation,
    SourceConfig,
    SourceRegistry,
    UnmappableTableError,
    aws_auth_field,
    detect,
    discovery_options_from,
    file_option_fields,
    frozen,
    lookup_s3_bucket_region,
    parse_s3_url,
    resolve_aws_credentials,
    source_caption,
    url_field,
)

# The IAM actions this source calls. A role session can use only these.
AWS_SESSION_ACTIONS = (
    "kms:Decrypt",
    "s3:Get*",
    "s3:List*",
)


@frozen
class _AmazonS3Auth:
    """Amazon S3's `aws_auth` block under the names the shared resolver reads.

    The source stored its keys as `access_key_id` and `secret_access_key` before the block existed,
    and the block keeps those names so that stored configs still lift into it.
    """

    block: AmazonS3AwsAuthConfig

    @property
    def selection(self) -> str:
        return self.block.selection

    @property
    def aws_access_key_id(self) -> str | None:
        return self.block.access_key_id

    @property
    def aws_secret_access_key(self) -> str | None:
        return self.block.secret_access_key

    @property
    def aws_session_token(self) -> str | None:
        return None

    @property
    def aws_integration_id(self) -> int | None:
        return self.block.aws_integration_id


@SourceRegistry.register
class AmazonS3Source(ObjectStorageSource[AmazonS3SourceConfig]):
    codebase_detection = detect(
        npm=("@aws-sdk/client-s3",),
        pypi=("s3fs",),
        cargo=("aws-sdk-s3",),
        go=("github.com/aws/aws-sdk-go-v2/service/s3",),
        maven=("software.amazon.awssdk:s3",),
    )

    api_docs_url = "https://docs.aws.amazon.com/AmazonS3/latest/API/Welcome.html"
    requires_team_feature_flag = FEATURE_FLAG
    self_managed_service = "s3"

    flat_stored_selects = AWS_FLAT_STORED_SELECTS
    aws_session_actions = AWS_SESSION_ACTIONS

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AMAZONS3

    @property
    def credential_kind(self) -> str | None:
        return "aws-s3"

    @property
    def connection_host_fields(self) -> list[str]:
        # The URL picks the bucket and region the stored key is sent to, so changing it must re-require the key.
        return ["url_pattern"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {**AWS_AUTH_NON_RETRYABLE_ERRORS, **super().get_non_retryable_errors()}

    def object_store_config(self, config: AmazonS3SourceConfig, team_id: int) -> ObjectStoreConfig:
        url = parse_s3_url(config.url_pattern)
        if url.region is None:
            url = dataclasses.replace(url, region=lookup_s3_bucket_region(url.bucket))
        try:
            credentials = resolve_aws_credentials(_AmazonS3Auth(block=config.aws_auth), team_id, AWS_SESSION_ACTIONS)
        except AwsAuthError as e:
            # The object storage probe reports this error type to the user and lets others escape.
            raise ObjectStorageError(str(e)) from e
        if isinstance(credentials, RoleCredentials):
            return ObjectStoreConfig.from_url(
                ObjectStoreProvider.S3, url, access_key_id="", secret_access_key="", role_credentials=credentials
            )
        return ObjectStoreConfig.from_url(
            ObjectStoreProvider.S3,
            url,
            access_key_id=credentials.access_key.strip(),
            secret_access_key=credentials.secret_key.strip(),
        )

    def discovery_options(self, config: AmazonS3SourceConfig) -> DiscoveryOptions:
        return discovery_options_from(config)

    def self_managed_connection_inputs(
        self, location: SelfManagedLocation, credential: SelfManagedCredential
    ) -> dict[str, Any]:
        if location.region is None:
            raise UnmappableTableError("the URL doesn't name the bucket's region")
        return {
            "url_pattern": f"https://s3.{location.region}.amazonaws.com/{location.bucket}/",
            "access_key_id": credential.access_key,
            "secret_access_key": credential.access_secret,
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AMAZONS3,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            keywords=["s3", "aws", *KEYWORDS],
            label="Amazon S3",
            caption=(
                f"{source_caption('an S3 bucket')} Connect with an IAM role or access keys that have `s3:ListBucket` "
                "on the bucket and `s3:GetObject` on its objects."
            ),
            iconPath="/static/services/aws-s3.png",
            releaseStatus=ReleaseStatus.ALPHA,
            featureFlag=FEATURE_FLAG,
            fields=cast(
                list[FieldType],
                [
                    url_field(
                        S3_EXAMPLE_URL,
                        "Paste the S3 URI (s3://...) or the object URL from the AWS console.",
                    ),
                    aws_auth_field(
                        access_key_id_name="access_key_id",
                        secret_access_key_name="secret_access_key",
                        session_token=False,
                    ),
                    *file_option_fields(),
                ],
            ),
        )
