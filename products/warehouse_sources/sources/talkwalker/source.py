from typing import cast

from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from products.warehouse_sources.sources.talkwalker._config import TalkwalkerSourceConfig


@SourceRegistry.register
class TalkwalkerSource(SimpleSource[TalkwalkerSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TALKWALKER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TALKWALKER,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Talkwalker",
            iconPath="/static/services/talkwalker.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
