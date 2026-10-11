from typing import cast

from sources.backblaze._config import BackblazeSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class BackblazeSource(SimpleSource[BackblazeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BACKBLAZE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BACKBLAZE,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            label="Backblaze B2",
            iconPath="/static/services/backblaze.png",
            keywords=["backblaze", "b2", "storage", "buckets"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
