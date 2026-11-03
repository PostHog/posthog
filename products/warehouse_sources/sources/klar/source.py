from typing import cast

from products.warehouse_sources.sources.klar._config import KlarSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class KlarSource(SimpleSource[KlarSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KLAR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.KLAR,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Klar",
            iconPath="/static/services/klar.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
