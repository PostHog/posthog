from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.azureresourcegraph import (
    AzureResourceGraphSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AzureResourceGraphSource(SimpleSource[AzureResourceGraphSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZURERESOURCEGRAPH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AZURE_RESOURCE_GRAPH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Azure (Azure Resource Graph)",
            iconPath="/static/services/azure_resource_graph.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
