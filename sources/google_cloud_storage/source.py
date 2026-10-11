from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.google_cloud_storage._config import GoogleCloudStorageSourceConfig


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
