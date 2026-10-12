from typing import cast

from sources.microsoft_teams._config import MicrosoftTeamsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MicrosoftTeamsSource(SimpleSource[MicrosoftTeamsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTTEAMS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MICROSOFTTEAMS,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            keywords=["ms teams", "teams"],
            label="Microsoft Teams",
            iconPath="/static/services/microsoft_teams.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
