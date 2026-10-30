import dataclasses
from typing import Any, cast

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
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.fields import (
    FEATURE_FLAG,
    KEYWORDS,
    discovery_options_from,
    file_option_fields,
    secret_field,
    source_caption,
    text_field,
    url_field,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.filesystem import (
    lookup_s3_bucket_region,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.locations import (
    S3_EXAMPLE_URL,
    parse_s3_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.self_managed import (
    SelfManagedCredential,
    SelfManagedLocation,
    UnmappableTableError,
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
    self_managed_service = "s3"

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

    def object_store_config(self, config: AmazonS3SourceConfig) -> ObjectStoreConfig:
        url = parse_s3_url(config.url_pattern)
        if url.region is None:
            url = dataclasses.replace(url, region=lookup_s3_bucket_region(url.bucket))
        return ObjectStoreConfig.from_url(
            ObjectStoreProvider.S3,
            url,
            access_key_id=config.access_key_id.strip(),
            secret_access_key=config.secret_access_key.strip(),
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
            caption=source_caption("an S3 bucket"),
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
                    text_field("access_key_id", "Access key ID", "AKIA..."),
                    secret_field("secret_access_key", "Secret access key"),
                    *file_option_fields(),
                ],
            ),
        )
