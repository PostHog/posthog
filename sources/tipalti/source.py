from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.tipalti._config import TipaltiSourceConfig


@SourceRegistry.register
class TipaltiSource(SimpleSource[TipaltiSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TIPALTI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TIPALTI,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Tipalti",
            iconPath="/static/services/tipalti.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
