from typing import cast

from sources.azure_data_explorer._config import AzureDataExplorerSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AzureDataExplorerSource(SimpleSource[AzureDataExplorerSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZUREDATAEXPLORER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AZUREDATAEXPLORER,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Microsoft Azure Data Explorer (Kusto)",
            iconPath="/static/services/azure_data_explorer.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
