from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.twitch._config import TwitchSourceConfig


@SourceRegistry.register
class TwitchSource(SimpleSource[TwitchSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TWITCH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TWITCH,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Twitch Interactive, Inc. (Twitch Helix API)",
            iconPath="/static/services/twitch.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
