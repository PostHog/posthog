from typing import cast

from sources.circle_so._config import CircleSoSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class CircleSoSource(SimpleSource[CircleSoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CIRCLESO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CIRCLESO,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Circle (circle.so)",
            iconPath="/static/services/circle_so.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
