from typing import cast

from sources.moodle._config import MoodleSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MoodleSource(SimpleSource[MoodleSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MOODLE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MOODLE,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Moodle",
            iconPath="/static/services/moodle.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
