from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.zoominfo._config import ZoomInfoSourceConfig


@SourceRegistry.register
class ZoomInfoSource(SimpleSource[ZoomInfoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZOOMINFO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ZOOMINFO,
            category=DataWarehouseSourceCategory.CRM,
            label="ZoomInfo",
            iconPath="/static/services/zoominfo.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
