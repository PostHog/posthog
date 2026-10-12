from typing import cast

from products.warehouse_sources.sources.azure_resource_health._config import AzureResourceHealthSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AzureResourceHealthSource(SimpleSource[AzureResourceHealthSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZURERESOURCEHEALTH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AZURERESOURCEHEALTH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Azure (Azure Resource Health / Service Health)",
            iconPath="/static/services/azure_resource_health.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
