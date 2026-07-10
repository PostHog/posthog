from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FireworksAISourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FireworksAISource(SimpleSource[FireworksAISourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FIREWORKSAI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FIREWORKS_AI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Fireworks AI",
            iconPath="/static/services/fireworks_ai.png",
            keywords=["llm", "inference", "fine-tuning", "ai"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
