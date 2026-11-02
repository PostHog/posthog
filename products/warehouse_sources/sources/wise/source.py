from typing import cast

from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from products.warehouse_sources.sources.wise._config import WiseSourceConfig


@SourceRegistry.register
class WiseSource(SimpleSource[WiseSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WISE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.WISE,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Wise",
            iconPath="/static/services/wise.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
