from typing import cast

from sources.doorloop._config import DoorloopSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class DoorloopSource(SimpleSource[DoorloopSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DOORLOOP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DOORLOOP,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="DoorLoop",
            iconPath="/static/services/doorloop.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
