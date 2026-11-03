from typing import cast

from products.warehouse_sources.sources.airship._config import AirshipSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AirshipSource(SimpleSource[AirshipSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AIRSHIP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AIRSHIP,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Airship",
            iconPath="/static/services/airship.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
