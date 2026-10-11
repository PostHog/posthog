from typing import cast

from sources.google_calendar._config import GoogleCalendarSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GoogleCalendarSource(SimpleSource[GoogleCalendarSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLECALENDAR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOOGLECALENDAR,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Google Calendar",
            iconPath="/static/services/google_calendar.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
