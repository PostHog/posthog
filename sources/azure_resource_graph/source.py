from typing import cast

from sources.azure_resource_graph._config import AzureResourceGraphSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AzureResourceGraphSource(SimpleSource[AzureResourceGraphSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZURERESOURCEGRAPH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AZURERESOURCEGRAPH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Azure (Azure Resource Graph)",
            iconPath="/static/services/azure_resource_graph.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
