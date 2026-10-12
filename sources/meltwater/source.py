from typing import cast

from sources.meltwater._config import MeltwaterSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MeltwaterSource(SimpleSource[MeltwaterSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MELTWATER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MELTWATER,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Meltwater",
            iconPath="/static/services/meltwater.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
