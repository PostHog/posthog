from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.castoredc import (
    CastorEDCSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CastorEDCSource(SimpleSource[CastorEDCSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CASTOREDC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CASTOREDC,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Castor EDC",
            iconPath="/static/services/castor_edc.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
