from typing import cast

from sources.loom._config import LoomSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class LoomSource(SimpleSource[LoomSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LOOM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LOOM,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Loom",
            iconPath="/static/services/loom.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
