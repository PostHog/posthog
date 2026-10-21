from typing import cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.config import (
    DiscoveryOptions,
    ObjectStoreConfig,
    ObjectStoreProvider,
    normalize_prefix,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.fields import (
    FEATURE_FLAG,
    KEYWORDS,
    discovery_options_from,
    file_option_fields,
    folder_fields,
    secret_field,
    source_caption,
    text_field,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.source_base import (
    ObjectStorageSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.amazons3 import (
    AmazonS3SourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


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
        return discovery_options_from(config)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AMAZONS3,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            keywords=["s3", "aws", *KEYWORDS],
            label="Amazon S3",
            caption=source_caption("an S3 bucket"),
            iconPath="/static/services/aws-s3.png",
            releaseStatus=ReleaseStatus.ALPHA,
            featureFlag=FEATURE_FLAG,
            fields=cast(
                list[FieldType],
                [
                    text_field("bucket", "Bucket", "my-company-exports"),
                    text_field("region", "Region", "us-east-1"),
                    *folder_fields("bucket"),
                    text_field("access_key_id", "Access key ID", "AKIA..."),
                    secret_field("secret_access_key", "Secret access key"),
                    *file_option_fields(),
                ],
            ),
        )
