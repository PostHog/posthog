from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.chargebackstop import (
    ChargebackStopSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ChargebackStopSource(SimpleSource[ChargebackStopSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CHARGEBACKSTOP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CHARGEBACKSTOP,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="ChargebackStop",
            iconPath="/static/services/chargebackstop.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
