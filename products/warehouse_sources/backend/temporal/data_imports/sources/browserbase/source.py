from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BrowserbaseSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BrowserbaseSource(SimpleSource[BrowserbaseSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BROWSERBASE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BROWSERBASE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Browserbase",
            iconPath="/static/services/browserbase.png",
            keywords=["browser", "automation", "agents", "sessions"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
