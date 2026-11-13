from typing import cast

from products.warehouse_sources.sources.cyberimpact._config import CyberimpactSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceKey,
    SourceRegistry,
    source_key,
)

SOURCE_KEY = "Cyberimpact"


@SourceRegistry.register
class CyberimpactSource(SimpleSource[CyberimpactSourceConfig]):
    api_docs_url = "https://api.cyberimpact.com/docs"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Cyberimpact",
            iconPath="/static/warehouse-sources/cyberimpact/icon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
