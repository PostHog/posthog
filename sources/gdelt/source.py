from typing import cast

from sources.gdelt._config import GdeltSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GdeltSource(SimpleSource[GdeltSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GDELT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GDELT,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="GDELT Project",
            iconPath="/static/services/gdelt.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
