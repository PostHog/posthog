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
from products.warehouse_sources.sources.sms_manager._config import SmsManagerSourceConfig

SOURCE_KEY = "SmsManager"


@SourceRegistry.register
class SmsManagerSource(SimpleSource[SmsManagerSourceConfig]):
    api_docs_url = "https://smsmanager.cz/api/"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="SMS Manager",
            iconPath="/static/warehouse-sources/sms_manager/icon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
