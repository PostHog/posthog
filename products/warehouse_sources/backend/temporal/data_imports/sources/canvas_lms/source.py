from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.canvaslms import (
    CanvasLmsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CanvasLmsSource(SimpleSource[CanvasLmsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CANVASLMS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CANVAS_LMS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Instructure Canvas LMS",
            iconPath="/static/services/canvas_lms.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
