from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigConverter,
    SourceFieldSelectConfigOption,
    SourceFieldSwitchGroupConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.config import (
    DiscoveryOptions,
    ObjectStoreConfig,
    ObjectStoreProvider,
    normalize_prefix,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.source_base import (
    ObjectStorageSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.amazons3 import (
    AmazonS3SourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

FEATURE_FLAG = "dwh-object-storage-sources"


@SourceRegistry.register
class AmazonS3Source(ObjectStorageSource[AmazonS3SourceConfig]):
    api_docs_url = "https://docs.aws.amazon.com/AmazonS3/latest/API/Welcome.html"
    requires_team_feature_flag = FEATURE_FLAG

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AMAZONS3

    @property
    def connection_host_fields(self) -> list[str]:
        # The bucket and region pick where the stored key is sent, so changing either must re-require it.
        return ["bucket", "region"]

    def object_store_config(self, config: AmazonS3SourceConfig) -> ObjectStoreConfig:
        return ObjectStoreConfig(
            provider=ObjectStoreProvider.S3,
            bucket=config.bucket.strip(),
            region=config.region.strip(),
            access_key_id=config.access_key_id.strip(),
            secret_access_key=config.secret_access_key.strip(),
            prefix=normalize_prefix(config.path),
        )

    def discovery_options(self, config: AmazonS3SourceConfig) -> DiscoveryOptions:
        combine = config.combine_files
        return DiscoveryOptions(
            file_format=config.file_format,
            file_pattern=(config.file_pattern or "").strip() or None,
            allow_double_quotes=config.csv_allow_double_quotes,
            combined_table_name=combine.table_name if combine is not None and combine.enabled else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AMAZONS3,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            keywords=["s3", "aws", "bucket", "parquet", "delta lake"],
            label="Amazon S3",
            caption=(
                "Import CSV, JSON Lines and Parquet files, and Delta Lake tables, from an S3 bucket. PostHog "
                "creates one table per folder, one per file at the top of the folder you choose, and one per "
                "Delta table. Every sync reads the files in full, so each table matches the bucket."
            ),
            iconPath="/static/services/aws-s3.png",
            releaseStatus=ReleaseStatus.ALPHA,
            featureFlag=FEATURE_FLAG,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="bucket",
                        label="Bucket",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-company-exports",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="region",
                        label="Region",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="us-east-1",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="path",
                        label="Folder (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="exports/",
                        caption="Leave it empty to import from the whole bucket.",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="file_pattern",
                        label="File pattern (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="*.parquet",
                        caption=(
                            "A glob matched against each file's path inside the folder, where * also matches "
                            "across folders. Leave it empty to import every file."
                        ),
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="access_key_id",
                        label="Access key ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="AKIA...",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="secret_access_key",
                        label="Secret access key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="file_format",
                        label="File format",
                        required=True,
                        defaultValue="infer",
                        options=[
                            SourceFieldSelectConfigOption(label="Detect from file extension", value="infer"),
                            SourceFieldSelectConfigOption(label="CSV with a header row", value="csv"),
                            SourceFieldSelectConfigOption(label="CSV without a header row", value="csv_no_header"),
                            SourceFieldSelectConfigOption(label="JSON Lines", value="jsonl"),
                            SourceFieldSelectConfigOption(label="Parquet", value="parquet"),
                            SourceFieldSelectConfigOption(label="Delta Lake", value="delta"),
                        ],
                    ),
                    SourceFieldSelectConfig(
                        name="csv_allow_double_quotes",
                        label="Do double quotes enclose CSV values?",
                        required=True,
                        defaultValue="true",
                        converter=SourceFieldSelectConfigConverter.STR_TO_BOOL,
                        options=[
                            SourceFieldSelectConfigOption(label="Yes", value="true"),
                            SourceFieldSelectConfigOption(label="No, treat them as plain text", value="false"),
                        ],
                    ),
                    SourceFieldSwitchGroupConfig(
                        name="combine_files",
                        label="Combine every file into one table?",
                        caption=(
                            "Turn this on when the folder holds files that share the same columns, such as a "
                            "daily export. Delta tables still get a table each."
                        ),
                        default=False,
                        fields=cast(
                            list[FieldType],
                            [
                                SourceFieldInputConfig(
                                    name="table_name",
                                    label="Table name",
                                    type=SourceFieldInputConfigType.TEXT,
                                    required=True,
                                    placeholder="orders",
                                    secret=False,
                                ),
                            ],
                        ),
                    ),
                ],
            ),
        )
