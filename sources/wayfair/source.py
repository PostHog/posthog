from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.wayfair._config import WayfairSourceConfig


@SourceRegistry.register
class WayfairSource(SimpleSource[WayfairSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WAYFAIR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.WAYFAIR,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Wayfair (Supplier / Partner API)",
            iconPath="/static/services/wayfair.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
