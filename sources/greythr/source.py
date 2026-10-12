from typing import cast

from sources.greythr._config import GreytHrSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GreytHrSource(SimpleSource[GreytHrSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GREYTHR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GREYTHR,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="GreytHr",
            iconPath="/static/services/greythr.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
