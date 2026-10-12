from typing import cast

from sources.google_tasks._config import GoogleTasksSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GoogleTasksSource(SimpleSource[GoogleTasksSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLETASKS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOOGLETASKS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Google Tasks",
            iconPath="/static/services/google_tasks.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
