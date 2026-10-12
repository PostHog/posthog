from typing import cast

from sources.mode._config import ModeSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class ModeSource(SimpleSource[ModeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MODE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MODE,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Mode",
            iconPath="/static/services/mode.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
