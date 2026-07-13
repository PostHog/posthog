from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import NorthflankSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NorthflankSource(SimpleSource[NorthflankSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NORTHFLANK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.NORTHFLANK,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Northflank",
            iconPath="/static/services/northflank.png",
            keywords=["deployment", "containers", "paas", "devops"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
