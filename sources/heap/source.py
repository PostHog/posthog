from typing import cast

from sources.heap._config import HeapSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class HeapSource(SimpleSource[HeapSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HEAP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.HEAP,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Heap",
            iconPath="/static/services/heap.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
