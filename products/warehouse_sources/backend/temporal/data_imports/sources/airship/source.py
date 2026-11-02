from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.airship import (
    AirshipSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


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
