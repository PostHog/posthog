from typing import cast

from products.warehouse_sources.sources.helpin._config import HelpinSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceKey,
    SourceRegistry,
    source_key,
)

SOURCE_KEY = "Helpin"


@SourceRegistry.register
class HelpinSource(SimpleSource[HelpinSourceConfig]):
    api_docs_url = "https://helpin.ai/docs/articles/developer-api-ab6265ea"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Helpin",
            iconPath="/static/warehouse-sources/helpin/icon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
