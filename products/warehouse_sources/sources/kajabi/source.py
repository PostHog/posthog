from typing import cast

from products.warehouse_sources.sources.kajabi._config import KajabiSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class KajabiSource(SimpleSource[KajabiSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KAJABI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.KAJABI,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Kajabi",
            iconPath="/static/services/kajabi.png",
            keywords=["courses", "memberships", "creator commerce"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
