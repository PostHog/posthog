from typing import cast

from products.warehouse_sources.sources.didit._config import DiditSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceKey,
    SourceRegistry,
    source_key,
)

SOURCE_KEY = "Didit"


@SourceRegistry.register
class DiditSource(SimpleSource[DiditSourceConfig]):
    api_docs_url = "https://docs.didit.me/sessions-api/overview"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Didit",
            iconPath="/static/warehouse-sources/didit/icon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
