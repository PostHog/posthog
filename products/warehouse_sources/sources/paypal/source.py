from typing import cast

from products.warehouse_sources.sources.paypal._config import PayPalSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class PayPalSource(SimpleSource[PayPalSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PAYPAL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PAYPAL,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="PayPal",
            iconPath="/static/services/paypal.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
