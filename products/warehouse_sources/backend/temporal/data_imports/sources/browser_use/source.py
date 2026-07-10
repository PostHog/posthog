from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BrowserUseSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BrowserUseSource(SimpleSource[BrowserUseSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BROWSERUSE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BROWSER_USE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Browser Use",
            iconPath="/static/services/browser_use.png",
            keywords=["browser automation", "ai agents", "agent runs", "web automation"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
