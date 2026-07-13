from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MetorialSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MetorialSource(SimpleSource[MetorialSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.METORIAL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.METORIAL,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Metorial",
            iconPath="/static/services/metorial.png",
            keywords=["mcp", "ai infrastructure", "agents", "observability"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
