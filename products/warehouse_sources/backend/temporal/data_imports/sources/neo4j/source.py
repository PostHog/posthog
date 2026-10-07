from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.neo4j import Neo4jSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class Neo4jSource(SimpleSource[Neo4jSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NEO4J

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NEO4J,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Neo4j",
            keywords=["graph database", "cypher"],
            iconPath="/static/services/neo4j.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
