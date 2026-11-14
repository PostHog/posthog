from typing import cast

from products.warehouse_sources.sources.fastspring._config import FastSpringSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceKey,
    SourceRegistry,
    source_key,
)

SOURCE_KEY = "FastSpring"


@SourceRegistry.register
class FastSpringSource(SimpleSource[FastSpringSourceConfig]):
    api_docs_url = "https://developer.fastspring.com/reference/api-overview"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def credential_kind(self) -> str | None:
        return "fastspring"

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="FastSpring",
            iconPath="/static/warehouse-sources/fastspring/icon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
