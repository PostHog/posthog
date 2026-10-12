from typing import cast

from sources.raken._config import RakenSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class RakenSource(SimpleSource[RakenSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RAKEN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.RAKEN,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Raken",
            iconPath="/static/services/raken.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
