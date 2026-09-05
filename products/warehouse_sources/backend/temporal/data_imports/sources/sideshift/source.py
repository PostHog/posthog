from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sideshift import (
    SideShiftSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SideShiftSource(SimpleSource[SideShiftSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SIDESHIFT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SIDESHIFT,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="SideShift",
            iconPath="/static/services/sideshift.png",
            keywords=["crypto", "exchange", "swaps"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
