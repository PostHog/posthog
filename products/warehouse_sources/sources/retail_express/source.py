from typing import cast

from products.warehouse_sources.sources.retail_express._config import RetailExpressSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class RetailExpressSource(SimpleSource[RetailExpressSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RETAILEXPRESS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.RETAILEXPRESS,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Retail Express",
            iconPath="/static/services/retail_express.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
