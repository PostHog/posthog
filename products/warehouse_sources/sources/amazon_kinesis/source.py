from typing import cast

from products.warehouse_sources.sources.amazon_kinesis._config import AmazonKinesisSourceConfig
from products.warehouse_sources.sources.amazon_kinesis.amazon_kinesis import (
    ERROR_PREFIX,
    KinesisClient,
    KinesisCursor,
    KinesisResumeState,
    amazon_kinesis_source,
    list_streams,
    validate_credentials as validate_amazon_kinesis_credentials,
)
from products.warehouse_sources.sources.amazon_kinesis.settings import (
    INCREMENTAL_FIELDS,
    KINESIS_API_VERSION,
    PRIMARY_KEYS,
    SYNC_ERROR_MESSAGES,
    THROTTLING_ERROR_CODES,
    TRANSIENT_ERROR_CODES,
)
from products.warehouse_sources.sources.sdk import (
    CursorSource,
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
    detect,
)


@SourceRegistry.register
class AmazonKinesisSource(ResumableSource[AmazonKinesisSourceConfig, KinesisResumeState], CursorSource[KinesisCursor]):
    codebase_detection = detect(
        env=("^(AWS_)?KINESIS_",),
        npm=("@aws-sdk/client-kinesis", "aws-kinesis-agg"),
        pypi=("amazon-kclpy", "aws-kinesis-agg"),
        cargo=("aws-sdk-kinesis",),
        go=("github.com/aws/aws-sdk-go-v2/service/kinesis",),
        maven=(
            "software.amazon.awssdk:kinesis",
            "software.amazon.kinesis:amazon-kinesis-client",
            "com.amazonaws:amazon-kinesis-producer",
        ),
        rubygems=("aws-sdk-kinesis",),
    )

    supported_versions = (KINESIS_API_VERSION,)
    default_version = KINESIS_API_VERSION
    api_docs_url = "https://docs.aws.amazon.com/kinesis/latest/APIReference/Welcome.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AMAZONKINESIS

    @property
    def connection_host_fields(self) -> list[str]:
        return ["aws_region"]

    def cursor_class(self) -> type[KinesisCursor]:
        return KinesisCursor

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {f"{ERROR_PREFIX}: {code}": message for code, message in SYNC_ERROR_MESSAGES.items()}

    def get_retryable_errors(self) -> set[str]:
        return {f"{ERROR_PREFIX}: {code}" for code in THROTTLING_ERROR_CODES | TRANSIENT_ERROR_CODES} | {
            f"{ERROR_PREFIX}: HTTP 5"
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AMAZONKINESIS,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Amazon Kinesis",
            caption="""Import the records of your Amazon Kinesis data streams. Each stream becomes a table, and each sync reads the records added since the last one. Records with a JSON object payload get a column for each key.

Create an IAM user whose policy allows `kinesis:ListStreams`, `kinesis:DescribeStreamSummary`, `kinesis:ListShards`, `kinesis:GetShardIterator` and `kinesis:GetRecords`, then paste its access key below. If a stream is encrypted with your own KMS key, also allow `kms:Decrypt` on that key.

Kinesis keeps records for 24 hours unless you raise the retention of the stream, so sync more often than that. Syncs share the read limits of each shard with your other consumers.""",
            iconPath="/static/services/aws-kinesis.png",
            docsUrl="https://posthog.com/docs/cdp/sources/amazon-kinesis",
            releaseStatus=ReleaseStatus.BETA,
            keywords=["aws", "streaming", "data streams", "kds"],
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
                        caption="Only for temporary credentials. Session tokens expire after a few hours, so scheduled syncs fail once the token expires. Use a permanent access key for recurring imports.",
                        secret=True,
                    ),
                ],
            ),
        )

    def _client(self, config: AmazonKinesisSourceConfig) -> KinesisClient:
        return KinesisClient(
            config.aws_access_key_id, config.aws_secret_access_key, config.aws_session_token, config.aws_region
        )

    def get_schemas(
        self,
        config: AmazonKinesisSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        streams = list_streams(self._client(config))
        return [
            SourceSchema(
                name=stream,
                supports_incremental=True,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS,
                detected_primary_keys=PRIMARY_KEYS,
            )
            for stream in streams
            if names is None or stream in names
        ]

    def validate_credentials(
        self,
        config: AmazonKinesisSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_amazon_kinesis_credentials(
            config.aws_access_key_id,
            config.aws_secret_access_key,
            config.aws_session_token,
            config.aws_region,
            schema_name,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[KinesisResumeState]:
        return ResumableSourceManager[KinesisResumeState](inputs, KinesisResumeState)

    def source_for_pipeline(
        self,
        config: AmazonKinesisSourceConfig,
        resumable_source_manager: ResumableSourceManager[KinesisResumeState],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return amazon_kinesis_source(
            client=self._client(config),
            stream_name=inputs.schema_name,
            resumable_source_manager=resumable_source_manager,
            cursor_manager=self.get_cursor_manager(inputs),
            use_cursor=inputs.should_use_incremental_field,
            logger=inputs.logger,
        )
