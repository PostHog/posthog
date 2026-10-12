from typing import cast

from sources.azure_monitor_alerts._config import AzureMonitorAlertsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AzureMonitorAlertsSource(SimpleSource[AzureMonitorAlertsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZUREMONITORALERTS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AZUREMONITORALERTS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Azure (Azure Monitor / Alerts Management)",
            iconPath="/static/services/azure_monitor_alerts.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
