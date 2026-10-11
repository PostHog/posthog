from typing import cast

from sources.liveblocks._config import LiveblocksSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class LiveblocksSource(SimpleSource[LiveblocksSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LIVEBLOCKS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LIVEBLOCKS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Liveblocks",
            iconPath="/static/services/liveblocks.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
