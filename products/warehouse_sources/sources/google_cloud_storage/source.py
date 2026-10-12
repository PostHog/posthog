from typing import cast

from products.warehouse_sources.sources.google_cloud_storage._config import GoogleCloudStorageSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GoogleCloudStorageSource(SimpleSource[GoogleCloudStorageSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLECLOUDSTORAGE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOOGLECLOUDSTORAGE,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            keywords=["gcs"],
            label="Google Cloud Storage",
            iconPath="/static/services/google-cloud-storage.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
