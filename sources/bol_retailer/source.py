from typing import cast

from sources.bol_retailer._config import BolRetailerSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class BolRetailerSource(SimpleSource[BolRetailerSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BOLRETAILER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BOLRETAILER,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="bol.com (bol Partner / Retailer API)",
            iconPath="/static/services/bol_retailer.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
