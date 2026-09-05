from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.revolutmerchant import (
    RevolutMerchantSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RevolutMerchantSource(SimpleSource[RevolutMerchantSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.REVOLUTMERCHANT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.REVOLUTMERCHANT,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Revolut Merchant",
            iconPath="/static/services/revolut_merchant.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
