from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HatchetSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HatchetSource(SimpleSource[HatchetSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HATCHET

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HATCHET,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Hatchet",
            iconPath="/static/services/hatchet.png",
            keywords=["task queue", "workflows", "orchestration", "background jobs"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
