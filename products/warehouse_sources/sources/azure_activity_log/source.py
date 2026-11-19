from typing import cast

from products.warehouse_sources.sources.azure_activity_log._config import AzureActivityLogSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AzureActivityLogSource(SimpleSource[AzureActivityLogSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZUREACTIVITYLOG

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AZUREACTIVITYLOG,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Azure (Azure Monitor)",
            iconPath="/static/services/azure_activity_log.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
