from typing import cast

from products.warehouse_sources.sources.bird._config import BirdSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceKey,
    SourceRegistry,
    source_key,
)

SOURCE_KEY = "Bird"


@SourceRegistry.register
class BirdSource(SimpleSource[BirdSourceConfig]):
    api_docs_url = "https://docs.bird.com/api"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Bird",
            iconPath="/static/warehouse-sources/bird/icon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
