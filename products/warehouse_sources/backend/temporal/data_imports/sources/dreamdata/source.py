from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dreamdata import (
    DreamdataSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DreamdataSource(SimpleSource[DreamdataSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DREAMDATA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DREAMDATA,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Dreamdata",
            iconPath="/static/services/dreamdata.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
