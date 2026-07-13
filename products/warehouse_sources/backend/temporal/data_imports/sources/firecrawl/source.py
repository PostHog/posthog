from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FirecrawlSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FirecrawlSource(SimpleSource[FirecrawlSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FIRECRAWL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FIRECRAWL,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Firecrawl",
            iconPath="/static/services/firecrawl.png",
            keywords=["scraping", "crawling", "web data", "firecrawl"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
