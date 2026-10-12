from typing import cast

from sources.dayforce._config import DayforceSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class DayforceSource(SimpleSource[DayforceSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DAYFORCE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DAYFORCE,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Dayforce (formerly Ceridian Dayforce)",
            iconPath="/static/services/dayforce.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
