from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CosmosDBSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CosmosDBSource(SimpleSource[CosmosDBSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.COSMOSDB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.COSMOS_DB,
            category=DataWarehouseSourceCategory.DATABASES,
            keywords=["azure cosmos"],
            label="Azure Cosmos DB",
            iconPath="/static/services/cosmosdb.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
