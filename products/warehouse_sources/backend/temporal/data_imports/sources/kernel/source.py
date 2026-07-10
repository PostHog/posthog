from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import KernelSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KernelSource(SimpleSource[KernelSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KERNEL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.KERNEL,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Kernel",
            iconPath="/static/services/kernel.png",
            keywords=["browser", "automation", "agents", "infrastructure"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
