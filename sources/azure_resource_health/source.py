from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.azure_resource_health._config import AzureResourceHealthSourceConfig


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
