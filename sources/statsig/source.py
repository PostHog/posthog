from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.statsig._config import StatsigSourceConfig


@SourceRegistry.register
class StatsigSource(SimpleSource[StatsigSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STATSIG

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.STATSIG,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Statsig",
            iconPath="/static/services/statsig.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
