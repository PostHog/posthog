from typing import cast

from products.warehouse_sources.sources.greythr._config import GreytHrSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GreytHrSource(SimpleSource[GreytHrSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GREYTHR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GREYTHR,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="GreytHr",
            iconPath="/static/services/greythr.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
