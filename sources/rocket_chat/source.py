from typing import cast

from sources.rocket_chat._config import RocketChatSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class RocketChatSource(SimpleSource[RocketChatSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ROCKETCHAT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ROCKETCHAT,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Rocket.Chat",
            iconPath="/static/services/rocket_chat.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
