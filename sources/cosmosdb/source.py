from typing import cast

from sources.cosmosdb._config import CosmosDBSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class CosmosDBSource(SimpleSource[CosmosDBSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.COSMOSDB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.COSMOSDB,
            category=DataWarehouseSourceCategory.DATABASES,
            keywords=["azure cosmos"],
            label="Azure Cosmos DB",
            iconPath="/static/services/cosmosdb.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
