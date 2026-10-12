from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.waiteraid._config import WaiteraidSourceConfig


@SourceRegistry.register
class WaiteraidSource(SimpleSource[WaiteraidSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WAITERAID

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.WAITERAID,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Waiteraid",
            iconPath="/static/services/waiteraid.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
