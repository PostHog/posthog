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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.locations import (
    GCS_EXAMPLE_URL,
    parse_gcs_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.self_managed import (
    SelfManagedCredential,
    SelfManagedLocation,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.object_store.source_base import (
    ObjectStorageSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googlecloudstorage import (
    GoogleCloudStorageSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GoogleCloudStorageSource(ObjectStorageSource[GoogleCloudStorageSourceConfig]):
    codebase_detection = detect(
        npm=("@google-cloud/storage",),
        pypi=("google-cloud-storage", "gcsfs"),
        go=("cloud.google.com/go/storage",),
        maven=("com.google.cloud:google-cloud-storage",),
    )

    api_docs_url = "https://cloud.google.com/storage/docs/interoperability"
    requires_team_feature_flag = FEATURE_FLAG
    self_managed_service = "gcs"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLECLOUDSTORAGE

    @property
    def connection_host_fields(self) -> list[str]:
        # The URL picks the bucket the stored key is sent to, so changing it must re-require the key.
        return ["url_pattern"]

    def object_store_config(self, config: GoogleCloudStorageSourceConfig) -> ObjectStoreConfig:
        return ObjectStoreConfig.from_url(
            ObjectStoreProvider.GCS,
            parse_gcs_url(config.url_pattern),
            access_key_id=config.access_key_id.strip(),
            secret_access_key=config.secret_access_key.strip(),
        )

    def discovery_options(self, config: GoogleCloudStorageSourceConfig) -> DiscoveryOptions:
        return discovery_options_from(config)

    def self_managed_connection_inputs(
        self, location: SelfManagedLocation, credential: SelfManagedCredential
    ) -> dict[str, Any]:
        return {
            "url_pattern": f"https://storage.googleapis.com/{location.bucket}/",
            "access_key_id": credential.access_key,
            "secret_access_key": credential.access_secret,
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOOGLECLOUDSTORAGE,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            keywords=["gcs", "google cloud", *KEYWORDS],
            label="Google Cloud Storage",
            caption=source_caption("a Google Cloud Storage bucket"),
            iconPath="/static/services/google-cloud-storage.png",
            releaseStatus=ReleaseStatus.ALPHA,
            featureFlag=FEATURE_FLAG,
            fields=cast(
                list[FieldType],
                [
                    url_field(GCS_EXAMPLE_URL),
                    text_field(
                        "access_key_id",
                        "HMAC access key",
                        "GOOG...",
                        caption=(
                            "Create an HMAC key in the Google Cloud console, under Cloud Storage settings, on "
                            "the Interoperability tab."
                        ),
                    ),
                    secret_field("secret_access_key", "HMAC secret"),
                    *file_option_fields(),
                ],
            ),
        )
