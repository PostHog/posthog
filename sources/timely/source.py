from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.timely._config import TimelySourceConfig


@SourceRegistry.register
class TimelySource(SimpleSource[TimelySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TIMELY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TIMELY,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Timely",
            iconPath="/static/services/timely.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
