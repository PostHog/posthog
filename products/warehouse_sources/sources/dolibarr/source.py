from typing import cast

from products.warehouse_sources.sources.dolibarr._config import DolibarrSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class DolibarrSource(SimpleSource[DolibarrSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DOLIBARR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DOLIBARR,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Dolibarr",
            iconPath="/static/services/dolibarr.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
