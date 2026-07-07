from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    GoogleCloudStorageSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GoogleCloudStorageSource(SimpleSource[GoogleCloudStorageSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLECLOUDSTORAGE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GOOGLE_CLOUD_STORAGE,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            keywords=["gcs"],
            label="Google Cloud Storage",
            iconPath="/static/services/google-cloud-storage.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
