from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.tinybird._config import TinybirdSourceConfig


@SourceRegistry.register
class TinybirdSource(SimpleSource[TinybirdSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TINYBIRD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TINYBIRD,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Tinybird",
            iconPath="/static/services/tinybird.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
