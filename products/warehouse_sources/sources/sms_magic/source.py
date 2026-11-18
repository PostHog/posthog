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
from products.warehouse_sources.sources.sms_magic._config import SmsMagicSourceConfig

SOURCE_KEY = "SmsMagic"


@SourceRegistry.register
class SmsMagicSource(SimpleSource[SmsMagicSourceConfig]):
    api_docs_url = "https://api.sms-magic.com/doc/"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="SMS-Magic",
            iconPath="/static/warehouse-sources/sms_magic/icon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
