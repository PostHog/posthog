from typing import cast

from sources.primetric._config import PrimetricSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class PrimetricSource(SimpleSource[PrimetricSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PRIMETRIC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PRIMETRIC,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Primetric",
            iconPath="/static/services/primetric.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
