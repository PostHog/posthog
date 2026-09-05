from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.semanticscholar import (
    SemanticScholarSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SemanticScholarSource(SimpleSource[SemanticScholarSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SEMANTICSCHOLAR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SEMANTICSCHOLAR,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Semantic Scholar (Allen Institute for AI)",
            iconPath="/static/services/semantic_scholar.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
