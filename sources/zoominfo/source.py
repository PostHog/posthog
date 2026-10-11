from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
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
