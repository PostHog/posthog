from typing import cast

from products.warehouse_sources.sources.preset._config import PresetSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class PresetSource(SimpleSource[PresetSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PRESET

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PRESET,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Preset (Apache Superset)",
            iconPath="/static/services/preset.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
