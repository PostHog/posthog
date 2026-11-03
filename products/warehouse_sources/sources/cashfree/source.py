from typing import cast

from products.warehouse_sources.sources.cashfree._config import CashfreeSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class CashfreeSource(SimpleSource[CashfreeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CASHFREE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CASHFREE,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Cashfree Payments (Cashfree Payments India Pvt Ltd)",
            iconPath="/static/services/cashfree.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
