from typing import cast

from sources.google_chat._config import GoogleChatSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GoogleChatSource(SimpleSource[GoogleChatSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLECHAT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOOGLECHAT,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Google Chat",
            iconPath="/static/services/google_chat.png",
            keywords=["chat", "messaging", "google workspace"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
