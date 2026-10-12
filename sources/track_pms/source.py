from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.track_pms._config import TrackPMSSourceConfig


@SourceRegistry.register
class TrackPMSSource(SimpleSource[TrackPMSSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TRACKPMS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TRACKPMS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Track PMS",
            iconPath="/static/services/track_pms.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
