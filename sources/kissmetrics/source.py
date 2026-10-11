from typing import cast

from sources.kissmetrics._config import KissmetricsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class KissmetricsSource(SimpleSource[KissmetricsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KISSMETRICS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.KISSMETRICS,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Kissmetrics",
            iconPath="/static/services/kissmetrics.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
