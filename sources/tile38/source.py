from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.tile38._config import Tile38SourceConfig


@SourceRegistry.register
class Tile38Source(SimpleSource[Tile38SourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TILE38

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TILE38,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Tile38",
            iconPath="/static/services/tile38.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
