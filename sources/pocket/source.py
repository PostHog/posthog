from typing import cast

from sources.pocket._config import PocketSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class PocketSource(SimpleSource[PocketSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.POCKET

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.POCKET,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Pocket",
            iconPath="/static/services/pocket.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
