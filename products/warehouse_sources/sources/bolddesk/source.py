from typing import cast

from products.warehouse_sources.sources.bolddesk._config import BoldDeskSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceKey,
    SourceRegistry,
    source_key,
)

SOURCE_KEY = "BoldDesk"


@SourceRegistry.register
class BoldDeskSource(SimpleSource[BoldDeskSourceConfig]):
    api_docs_url = "https://developer.bolddesk.com/api"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def credential_kind(self) -> str | None:
        return "bolddesk"

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="BoldDesk",
            iconPath="/static/warehouse-sources/bolddesk/icon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
