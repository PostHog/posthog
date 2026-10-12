from typing import cast

from sources.azure_monitor_metrics._config import AzureMonitorMetricsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AzureMonitorMetricsSource(SimpleSource[AzureMonitorMetricsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZUREMONITORMETRICS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AZUREMONITORMETRICS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Azure Monitor",
            iconPath="/static/services/azure_monitor_metrics.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
