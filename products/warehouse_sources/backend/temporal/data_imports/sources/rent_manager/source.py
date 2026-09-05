from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rentmanager import (
    RentManagerSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RentManagerSource(SimpleSource[RentManagerSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RENTMANAGER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.RENTMANAGER,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Rent Manager (London Computer Systems)",
            iconPath="/static/services/rent_manager.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
