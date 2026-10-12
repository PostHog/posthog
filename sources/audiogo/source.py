from typing import cast

from sources.audiogo._config import AudioGOSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AudioGOSource(SimpleSource[AudioGOSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AUDIOGO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AUDIOGO,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="AudioGO",
            iconPath="/static/services/audiogo.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
