from typing import cast

from sources.metricool._config import MetricoolSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MetricoolSource(SimpleSource[MetricoolSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.METRICOOL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.METRICOOL,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Metricool",
            iconPath="/static/services/metricool.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
