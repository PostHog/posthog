from typing import cast

from products.warehouse_sources.sources.invoca._config import InvocaSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceKey,
    SourceRegistry,
    source_key,
)

SOURCE_KEY = "Invoca"


@SourceRegistry.register
class InvocaSource(SimpleSource[InvocaSourceConfig]):
    api_docs_url = "https://developers.invoca.net/en/latest/api_documentation/index.html"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Invoca",
            iconPath="/static/warehouse-sources/invoca/icon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
