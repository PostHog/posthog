from typing import cast

from sources.pivotal_tracker._config import PivotalTrackerSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class PivotalTrackerSource(SimpleSource[PivotalTrackerSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PIVOTALTRACKER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PIVOTALTRACKER,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Pivotal Tracker",
            iconPath="/static/services/pivotal_tracker.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
