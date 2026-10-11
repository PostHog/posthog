from typing import cast

from sources.reddit._config import RedditSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class RedditSource(SimpleSource[RedditSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.REDDIT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.REDDIT,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Reddit",
            iconPath="/static/services/reddit.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
