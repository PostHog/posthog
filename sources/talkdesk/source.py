from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.talkdesk._config import TalkdeskSourceConfig


@SourceRegistry.register
class TalkdeskSource(SimpleSource[TalkdeskSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TALKDESK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TALKDESK,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Talkdesk",
            iconPath="/static/services/talkdesk.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
