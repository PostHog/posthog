from typing import cast

from products.warehouse_sources.sources.ninjaone_rmm._config import NinjaOneRMMSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class NinjaOneRMMSource(SimpleSource[NinjaOneRMMSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NINJAONERMM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NINJAONERMM,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="NinjaOne RMM",
            iconPath="/static/services/ninjaone_rmm.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
