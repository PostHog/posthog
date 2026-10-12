from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.threads._config import ThreadsSourceConfig


@SourceRegistry.register
class ThreadsSource(SimpleSource[ThreadsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.THREADS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.THREADS,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Meta Platforms (Threads API)",
            iconPath="/static/services/threads.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
