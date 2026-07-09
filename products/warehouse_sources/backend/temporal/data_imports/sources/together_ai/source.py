from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TogetherAISourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TogetherAISource(SimpleSource[TogetherAISourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TOGETHERAI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TOGETHER_AI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Together AI",
            iconPath="/static/services/together_ai.png",
            keywords=["ai", "llm", "inference", "fine-tuning"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
