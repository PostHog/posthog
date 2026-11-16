from typing import cast

from products.warehouse_sources.sources.better_auth._config import BetterAuthSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceKey,
    SourceRegistry,
    source_key,
)

SOURCE_KEY = "BetterAuth"


@SourceRegistry.register
class BetterAuthSource(SimpleSource[BetterAuthSourceConfig]):
    api_docs_url = "https://better-auth.com/docs/infrastructure/introduction"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Better Auth",
            iconPath="/static/warehouse-sources/better_auth/icon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
