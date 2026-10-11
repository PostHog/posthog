from typing import cast

from sources.meetup._config import MeetupSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MeetupSource(SimpleSource[MeetupSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MEETUP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MEETUP,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Meetup (Meetup.com, a Bending Spoons company)",
            iconPath="/static/services/meetup.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
