from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.calendarific import (
    CalendarificSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CalendarificSource(SimpleSource[CalendarificSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CALENDARIFIC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CALENDARIFIC,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Calendarific",
            iconPath="/static/services/calendarific.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
