from typing import cast

from sources.discord._config import DiscordSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class DiscordSource(SimpleSource[DiscordSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DISCORD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DISCORD,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Discord",
            iconPath="/static/services/discord.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
