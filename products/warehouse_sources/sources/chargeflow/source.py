from typing import cast

from products.warehouse_sources.sources.chargeflow._config import ChargeflowSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class ChargeflowSource(SimpleSource[ChargeflowSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CHARGEFLOW

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CHARGEFLOW,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Chargeflow",
            iconPath="/static/services/chargeflow.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
