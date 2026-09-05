from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sharepoint import (
    SharePointSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SharePointSource(SimpleSource[SharePointSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SHAREPOINT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SHAREPOINT,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            label="SharePoint",
            iconPath="/static/services/sharepoint.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
