from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.uploadcare import (
    UploadcareSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class UploadcareSource(SimpleSource[UploadcareSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.UPLOADCARE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.UPLOADCARE,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            label="Uploadcare",
            keywords=["uploadcare.com"],
            iconPath="/static/services/uploadcare.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
