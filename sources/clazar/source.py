from typing import cast

from sources.clazar._config import ClazarSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class ClazarSource(SimpleSource[ClazarSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLAZAR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CLAZAR,
            category=DataWarehouseSourceCategory.SALES,
            label="Clazar",
            iconPath="/static/services/clazar.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
