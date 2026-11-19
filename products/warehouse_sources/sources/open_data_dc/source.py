from typing import cast

from products.warehouse_sources.sources.open_data_dc._config import OpenDataDcSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class OpenDataDcSource(SimpleSource[OpenDataDcSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OPENDATADC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.OPENDATADC,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Open Data DC",
            iconPath="/static/services/open_data_dc.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
