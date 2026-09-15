from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.electricitymaps import (
    ElectricityMapsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ElectricityMapsSource(SimpleSource[ElectricityMapsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ELECTRICITYMAPS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ELECTRICITY_MAPS,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Electricity Maps",
            keywords=["carbon intensity", "grid", "electricity map"],
            iconPath="/static/services/electricity_maps.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
