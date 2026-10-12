from typing import cast

from sources.azure_api_management._config import AzureApiManagementSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AzureApiManagementSource(SimpleSource[AzureApiManagementSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZUREAPIMANAGEMENT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AZUREAPIMANAGEMENT,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Azure API Management",
            iconPath="/static/services/azure_api_management.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
