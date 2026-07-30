from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.azuredataexplorer import (
    AzureDataExplorerSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AzureDataExplorerSource(SimpleSource[AzureDataExplorerSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZUREDATAEXPLORER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AZURE_DATA_EXPLORER,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Microsoft Azure Data Explorer (Kusto)",
            iconPath="/static/services/azure_data_explorer.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
