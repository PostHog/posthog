from typing import cast

from sources.cart_com._config import CartComSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class CartComSource(SimpleSource[CartComSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CARTCOM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CARTCOM,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Cart.com",
            iconPath="/static/services/cart_com.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
