from typing import cast

from products.warehouse_sources.sources.blacksmith._config import BlacksmithSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceKey,
    SourceRegistry,
    source_key,
)

SOURCE_KEY = "Blacksmith"


@SourceRegistry.register
class BlacksmithSource(SimpleSource[BlacksmithSourceConfig]):
    api_docs_url = "https://docs.blacksmith.sh/blacksmith-cli/usage"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Blacksmith",
            iconPath="/static/warehouse-sources/blacksmith/icon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
