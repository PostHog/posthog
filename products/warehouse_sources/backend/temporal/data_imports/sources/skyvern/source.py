from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SkyvernSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SkyvernSource(SimpleSource[SkyvernSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SKYVERN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SKYVERN,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Skyvern",
            iconPath="/static/services/skyvern.png",
            keywords=["browser automation", "ai agent", "rpa", "workflows"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
