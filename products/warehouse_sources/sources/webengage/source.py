from typing import cast

from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceKey,
    SourceRegistry,
    source_key,
)
from products.warehouse_sources.sources.webengage._config import WebengageSourceConfig

SOURCE_KEY = "Webengage"


@SourceRegistry.register
class WebengageSource(SimpleSource[WebengageSourceConfig]):
    api_docs_url = "https://docs.webengage.com/docs/rest-api-getting-started"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="WebEngage",
            iconPath="/static/warehouse-sources/webengage/icon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
