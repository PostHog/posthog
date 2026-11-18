from typing import cast

from products.warehouse_sources.sources.bugsink._config import BugsinkSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceKey,
    SourceRegistry,
    source_key,
)

SOURCE_KEY = "Bugsink"


@SourceRegistry.register
class BugsinkSource(SimpleSource[BugsinkSourceConfig]):
    api_docs_url = "https://www.bugsink.com/docs/api/"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Bugsink",
            iconPath="/static/warehouse-sources/bugsink/icon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
