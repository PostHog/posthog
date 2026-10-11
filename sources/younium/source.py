from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.younium._config import YouniumSourceConfig


@SourceRegistry.register
class YouniumSource(SimpleSource[YouniumSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.YOUNIUM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.YOUNIUM,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Younium",
            iconPath="/static/services/younium.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
