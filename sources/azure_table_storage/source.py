from typing import cast

from sources.azure_table_storage._config import AzureTableStorageSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AzureTableStorageSource(SimpleSource[AzureTableStorageSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZURETABLESTORAGE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AZURETABLESTORAGE,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Azure Table Storage",
            iconPath="/static/services/azure_table_storage.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
