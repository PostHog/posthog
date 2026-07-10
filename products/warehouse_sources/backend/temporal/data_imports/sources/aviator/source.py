from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AviatorSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AviatorSource(SimpleSource[AviatorSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AVIATOR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AVIATOR,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Aviator",
            iconPath="/static/services/aviator.png",
            keywords=["merge queue", "pull requests", "ci", "developer productivity"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
