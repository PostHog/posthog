from typing import cast

from sources.microsoft_teams_call_records._config import MicrosoftTeamsCallRecordsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MicrosoftTeamsCallRecordsSource(SimpleSource[MicrosoftTeamsCallRecordsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTTEAMSCALLRECORDS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MICROSOFTTEAMSCALLRECORDS,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Microsoft (Microsoft Graph / Teams)",
            iconPath="/static/services/microsoft_teams_call_records.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
