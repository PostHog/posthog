from typing import cast

from sources.google_classroom._config import GoogleClassroomSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GoogleClassroomSource(SimpleSource[GoogleClassroomSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLECLASSROOM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOOGLECLASSROOM,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Google Classroom",
            iconPath="/static/services/google_classroom.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
