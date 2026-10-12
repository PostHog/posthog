from typing import cast

from sources.dragonboat._config import DragonboatSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class DragonboatSource(SimpleSource[DragonboatSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DRAGONBOAT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DRAGONBOAT,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            iconPath="/static/services/dragonboat.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
