from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.strava._config import StravaSourceConfig


@SourceRegistry.register
class StravaSource(SimpleSource[StravaSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STRAVA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.STRAVA,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Strava",
            iconPath="/static/services/strava.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
