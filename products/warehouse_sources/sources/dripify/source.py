from typing import cast

from products.warehouse_sources.sources.dripify._config import DripifySourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class DripifySource(SimpleSource[DripifySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DRIPIFY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DRIPIFY,
            category=DataWarehouseSourceCategory.SALES,
            label="Dripify",
            iconPath="/static/services/dripify.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
