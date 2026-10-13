from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rainforestpay import (
    RainforestPaySourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RainforestPaySource(SimpleSource[RainforestPaySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RAINFORESTPAY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.RAINFORESTPAY,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            keywords=["rainforest pay"],
            label="Rainforest",
            iconPath="/static/services/rainforest_pay.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
