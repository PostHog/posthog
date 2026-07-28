from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.catchpoint import (
    CatchpointSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CatchpointSource(SimpleSource[CatchpointSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CATCHPOINT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CATCHPOINT,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Catchpoint Systems",
            iconPath="/static/services/catchpoint.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
