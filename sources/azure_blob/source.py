from typing import cast

from sources.azure_blob._config import AzureBlobSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AzureBlobSource(SimpleSource[AzureBlobSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZUREBLOB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AZUREBLOB,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            label="Azure Blob",
            iconPath="/static/services/azure_blob.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
