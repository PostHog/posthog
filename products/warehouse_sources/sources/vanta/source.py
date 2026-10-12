from typing import cast

from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from products.warehouse_sources.sources.vanta._config import VantaSourceConfig


@SourceRegistry.register
class VantaSource(SimpleSource[VantaSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.VANTA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.VANTA,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Vanta",
            iconPath="/static/services/vanta.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
