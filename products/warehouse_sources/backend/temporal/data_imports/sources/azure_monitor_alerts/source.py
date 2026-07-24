from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.azuremonitoralerts import (
    AzureMonitorAlertsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AzureMonitorAlertsSource(SimpleSource[AzureMonitorAlertsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZUREMONITORALERTS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AZURE_MONITOR_ALERTS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Azure (Azure Monitor / Alerts Management)",
            iconPath="/static/services/azure_monitor_alerts.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
