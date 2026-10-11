from typing import cast

from sources.display_video_360._config import DisplayVideo360SourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class DisplayVideo360Source(SimpleSource[DisplayVideo360SourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DISPLAYVIDEO360

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DISPLAYVIDEO360,
            category=DataWarehouseSourceCategory.ADVERTISING,
            keywords=["dv360"],
            label="Display & Video 360",
            iconPath="/static/services/display_video_360.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
