from typing import cast

from sources.azure_synapse._config import AzureSynapseSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AzureSynapseSource(SimpleSource[AzureSynapseSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZURESYNAPSE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AZURESYNAPSE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Azure Synapse Analytics",
            iconPath="/static/services/azure_synapse.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
