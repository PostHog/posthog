from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MistralAISourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MistralAISource(SimpleSource[MistralAISourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MISTRALAI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MISTRAL_AI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Mistral AI",
            iconPath="/static/services/mistral_ai.png",
            keywords=["llm", "ai", "fine-tuning", "mistral"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
