from typing import cast

from sources.latitude._config import LatitudeSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class LatitudeSource(SimpleSource[LatitudeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LATITUDE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LATITUDE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Latitude",
            iconPath="/static/services/latitude.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
