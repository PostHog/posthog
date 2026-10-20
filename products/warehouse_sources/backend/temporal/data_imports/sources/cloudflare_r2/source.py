from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.config import (
    AUTO_REGION,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudflarer2 import (
    CloudflareR2SourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CloudflareR2Source(ObjectStorageSource[CloudflareR2SourceConfig]):
    api_docs_url = "https://developers.cloudflare.com/r2/api/s3/api/"
    requires_team_feature_flag = FEATURE_FLAG

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLOUDFLARER2

    @property
    def connection_host_fields(self) -> list[str]:
        # The account and bucket pick where the stored key is sent, so changing either must re-require it.
        return ["account_id", "bucket"]

    def object_store_config(self, config: CloudflareR2SourceConfig) -> ObjectStoreConfig:
        return ObjectStoreConfig(
            provider=ObjectStoreProvider.R2,
            bucket=config.bucket.strip(),
            region=AUTO_REGION,
            access_key_id=config.access_key_id.strip(),
            secret_access_key=config.secret_access_key.strip(),
            prefix=normalize_prefix(config.path),
            account_id=config.account_id.strip().lower(),
        )

    def discovery_options(self, config: CloudflareR2SourceConfig) -> DiscoveryOptions:
        return discovery_options_from(config)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CLOUDFLARER2,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            keywords=["r2", "cloudflare", *KEYWORDS],
            label="Cloudflare R2",
            caption=source_caption("a Cloudflare R2 bucket"),
            iconPath="/static/services/cloudflare.png",
            releaseStatus=ReleaseStatus.ALPHA,
            featureFlag=FEATURE_FLAG,
            fields=cast(
                list[FieldType],
                [
                    text_field(
                        "account_id",
                        "Account ID",
                        "",
                        caption="The 32-character ID on the R2 overview page of the Cloudflare dashboard.",
                    ),
                    text_field("bucket", "Bucket", "my-company-exports"),
                    *folder_fields("bucket"),
                    text_field(
                        "access_key_id",
                        "Access key ID",
                        "",
                        caption="Create an R2 API token with read access to the bucket, then copy its S3 credentials.",
                    ),
                    secret_field("secret_access_key", "Secret access key"),
                    *file_option_fields(),
                ],
            ),
        )
