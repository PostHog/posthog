from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudinary import (
    CloudinarySourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CloudinarySource(SimpleSource[CloudinarySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLOUDINARY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CLOUDINARY,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            label="Cloudinary",
            keywords=["cloudinary.com"],
            iconPath="/static/services/cloudinary.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
