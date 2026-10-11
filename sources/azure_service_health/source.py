from typing import cast

from sources.azure_service_health._config import AzureServiceHealthSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AzureServiceHealthSource(SimpleSource[AzureServiceHealthSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZURESERVICEHEALTH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AZURESERVICEHEALTH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Azure (Azure Service Health / Resource Health)",
            iconPath="/static/services/azure_service_health.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
