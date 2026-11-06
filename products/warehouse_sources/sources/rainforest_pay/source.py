from typing import cast

from products.warehouse_sources.sources.rainforest_pay._config import RainforestPaySourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


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
