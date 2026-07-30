from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.buymeacoffee import (
    BuyMeACoffeeSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BuyMeACoffeeSource(SimpleSource[BuyMeACoffeeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BUYMEACOFFEE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BUY_ME_A_COFFEE,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Buy Me a Coffee",
            iconPath="/static/services/buy_me_a_coffee.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
