from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.spotio import SpotIoSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SpotIoSource(SimpleSource[SpotIoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SPOTIO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SPOT_IO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Spot by Flexera (Spotinst)",
            iconPath="/static/services/spot_io.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
