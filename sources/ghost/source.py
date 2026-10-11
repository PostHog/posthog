from typing import cast

from sources.ghost._config import GhostSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GhostSource(SimpleSource[GhostSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GHOST

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GHOST,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Ghost (Ghost Foundation)",
            iconPath="/static/services/ghost.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
