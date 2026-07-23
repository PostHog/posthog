from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.midtrans import (
    MidtransSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MidtransSource(SimpleSource[MidtransSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MIDTRANS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MIDTRANS,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Midtrans (GoTo Financial / PT Midtrans)",
            iconPath="/static/services/midtrans.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
