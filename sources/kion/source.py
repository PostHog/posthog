from typing import cast

from sources.kion._config import KionSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class KionSource(SimpleSource[KionSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KION

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.KION,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Kion (formerly cloudtamer.io)",
            iconPath="/static/services/kion.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
