from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.youtube_data._config import YoutubeDataSourceConfig


@SourceRegistry.register
class YoutubeDataSource(SimpleSource[YoutubeDataSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.YOUTUBEDATA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.YOUTUBEDATA,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="YouTube Data",
            iconPath="/static/services/youtube_data.png",
            keywords=["youtube", "yt"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
