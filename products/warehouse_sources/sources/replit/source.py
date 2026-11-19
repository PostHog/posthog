from typing import cast

from products.warehouse_sources.sources.replit._config import ReplitSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceKey,
    SourceRegistry,
    source_key,
)

SOURCE_KEY = "Replit"


@SourceRegistry.register
class ReplitSource(SimpleSource[ReplitSourceConfig]):
    api_docs_url = "https://docs.replit.com/teams/identity-and-access-management/compliance-api"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Replit",
            iconPath="/static/warehouse-sources/replit/icon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
