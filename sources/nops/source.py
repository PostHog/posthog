from typing import cast

from sources.nops._config import NopsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class NopsSource(SimpleSource[NopsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NOPS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NOPS,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="nOps",
            iconPath="/static/services/nops.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
