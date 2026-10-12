from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.ticktick._config import TickTickSourceConfig


@SourceRegistry.register
class TickTickSource(SimpleSource[TickTickSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TICKTICK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TICKTICK,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="TickTick",
            iconPath="/static/services/ticktick.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
