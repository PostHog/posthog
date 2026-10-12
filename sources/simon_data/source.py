from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.simon_data._config import SimonDataSourceConfig


@SourceRegistry.register
class SimonDataSource(SimpleSource[SimonDataSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SIMONDATA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SIMONDATA,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Simon Data",
            iconPath="/static/services/simon_data.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
