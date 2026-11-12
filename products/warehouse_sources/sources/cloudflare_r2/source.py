from typing import Any, cast

from products.warehouse_sources.sources.cloudflare_r2._config import CloudflareR2SourceConfig
from products.warehouse_sources.sources.sdk import (
    KEYWORDS,
    R2_EXAMPLE_URL,
    DataWarehouseSourceCategory,
    DiscoveryOptions,
    ExternalDataSourceType,
    FieldType,
    ObjectStorageSource,
    ObjectStoreConfig,
    ObjectStoreProvider,
    ReleaseStatus,
    SelfManagedCredential,
    SelfManagedLocation,
    SourceConfig,
    SourceRegistry,
    detect,
    discovery_options_from,
    file_option_fields,
    parse_r2_url,
    secret_field,
    source_caption,
    text_field,
    url_field,
)


@SourceRegistry.register
class CloudflareR2Source(ObjectStorageSource[CloudflareR2SourceConfig]):
    # R2 is read with the S3 SDKs, so only its own .env keys tell it apart from S3.
    codebase_detection = detect(env=("^R2_", "^CLOUDFLARE_R2_"))

    api_docs_url = "https://developers.cloudflare.com/r2/api/s3/api/"
    self_managed_service = "r2"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLOUDFLARER2

    @property
    def connection_host_fields(self) -> list[str]:
        # The URL picks the account and bucket the stored key is sent to, so changing it must re-require the key.
        return ["url_pattern"]

    def object_store_config(self, config: CloudflareR2SourceConfig) -> ObjectStoreConfig:
        return ObjectStoreConfig.from_url(
            ObjectStoreProvider.R2,
            parse_r2_url(config.url_pattern),
            access_key_id=config.access_key_id.strip(),
            secret_access_key=config.secret_access_key.strip(),
        )

    def discovery_options(self, config: CloudflareR2SourceConfig) -> DiscoveryOptions:
        return discovery_options_from(config)

    def self_managed_connection_inputs(
        self, location: SelfManagedLocation, credential: SelfManagedCredential
    ) -> dict[str, Any]:
        jurisdiction = f".{location.jurisdiction}" if location.jurisdiction else ""
        return {
            "url_pattern": f"https://{location.account or ''}{jurisdiction}.r2.cloudflarestorage.com/{location.bucket}/",
            "access_key_id": credential.access_key,
            "secret_access_key": credential.access_secret,
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CLOUDFLARER2,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            keywords=["r2", "cloudflare", *KEYWORDS],
            label="Cloudflare R2",
            caption=source_caption("a Cloudflare R2 bucket"),
            iconPath="/static/services/cloudflare.png",
            releaseStatus=ReleaseStatus.GA,
            fields=cast(
                list[FieldType],
                [
                    url_field(R2_EXAMPLE_URL),
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
