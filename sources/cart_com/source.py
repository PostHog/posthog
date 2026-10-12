from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.cart_com._config import CartComSourceConfig


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
