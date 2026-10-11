from typing import cast

from sources.podbean._config import PodbeanSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class PodbeanSource(SimpleSource[PodbeanSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PODBEAN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PODBEAN,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Podbean",
            iconPath="/static/services/podbean.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
