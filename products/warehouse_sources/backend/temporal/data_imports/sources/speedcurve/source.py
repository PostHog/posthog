from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.speedcurve import (
    SpeedcurveSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SpeedcurveSource(SimpleSource[SpeedcurveSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SPEEDCURVE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SPEEDCURVE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="SpeedCurve",
            iconPath="/static/services/speedcurve.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
