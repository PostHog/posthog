from typing import cast

from sources.gumloop._config import GumloopSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GumloopSource(SimpleSource[GumloopSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GUMLOOP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GUMLOOP,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Gumloop",
            iconPath="/static/services/gumloop.png",
            keywords=["automation", "workflow", "ai", "no-code"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
