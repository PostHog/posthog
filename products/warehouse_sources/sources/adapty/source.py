from typing import cast

from products.warehouse_sources.sources.adapty._config import AdaptySourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AdaptySource(SimpleSource[AdaptySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ADAPTY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ADAPTY,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Adapty",
            iconPath="/static/services/adapty.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
