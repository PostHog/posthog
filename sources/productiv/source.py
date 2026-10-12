from typing import cast

from sources.productiv._config import ProductivSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class ProductivSource(SimpleSource[ProductivSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PRODUCTIV

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PRODUCTIV,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Productiv",
            iconPath="/static/services/productiv.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
