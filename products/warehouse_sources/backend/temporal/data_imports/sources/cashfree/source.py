from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cashfree import (
    CashfreeSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CashfreeSource(SimpleSource[CashfreeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CASHFREE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CASHFREE,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Cashfree Payments (Cashfree Payments India Pvt Ltd)",
            iconPath="/static/services/cashfree.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
