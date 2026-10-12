from typing import cast

from sources.logrocket._config import LogrocketSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class LogrocketSource(SimpleSource[LogrocketSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LOGROCKET

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LOGROCKET,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="LogRocket",
            iconPath="/static/services/logrocket.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
