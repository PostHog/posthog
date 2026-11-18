from typing import cast

from products.warehouse_sources.sources.emplifi._config import EmplifiSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceKey,
    SourceRegistry,
    source_key,
)

SOURCE_KEY = "Emplifi"


@SourceRegistry.register
class EmplifiSource(SimpleSource[EmplifiSourceConfig]):
    api_docs_url = "https://api.emplifi.io/"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Emplifi",
            iconPath="/static/warehouse-sources/emplifi/icon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
