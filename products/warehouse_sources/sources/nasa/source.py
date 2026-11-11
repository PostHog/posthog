from typing import cast

from products.warehouse_sources.sources.nasa._config import NasaSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class NasaSource(SimpleSource[NasaSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NASA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NASA,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="NASA",
            iconPath="/static/services/nasa.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
