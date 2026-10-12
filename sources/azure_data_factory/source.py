from typing import cast

from sources.azure_data_factory._config import AzureDataFactorySourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AzureDataFactorySource(SimpleSource[AzureDataFactorySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZUREDATAFACTORY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AZUREDATAFACTORY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Azure Data Factory",
            iconPath="/static/services/azure_data_factory.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
