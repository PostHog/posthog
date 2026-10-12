from typing import cast

from sources.repairshopr._config import RepairshoprSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class RepairshoprSource(SimpleSource[RepairshoprSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.REPAIRSHOPR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.REPAIRSHOPR,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Repairshopr",
            iconPath="/static/services/repairshopr.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
