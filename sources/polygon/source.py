from typing import cast

from sources.polygon._config import PolygonSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class PolygonSource(SimpleSource[PolygonSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.POLYGON

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.POLYGON,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Polygon.io",
            iconPath="/static/services/polygon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
