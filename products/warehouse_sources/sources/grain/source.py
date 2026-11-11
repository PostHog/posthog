from typing import cast

from products.warehouse_sources.sources.grain._config import GrainSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceKey,
    SourceRegistry,
    source_key,
)

SOURCE_KEY = "Grain"


@SourceRegistry.register
class GrainSource(SimpleSource[GrainSourceConfig]):
    api_docs_url = "https://developers.grain.com/versions.html"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Grain",
            iconPath="/static/warehouse-sources/grain/icon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
