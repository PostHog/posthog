from typing import cast

from sources.learnworlds._config import LearnworldsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class LearnworldsSource(SimpleSource[LearnworldsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LEARNWORLDS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LEARNWORLDS,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="LearnWorlds",
            iconPath="/static/services/learnworlds.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
