from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HyperspellSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HyperspellSource(SimpleSource[HyperspellSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HYPERSPELL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HYPERSPELL,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Hyperspell",
            iconPath="/static/services/hyperspell.png",
            keywords=["ai", "memory", "agents", "context"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
