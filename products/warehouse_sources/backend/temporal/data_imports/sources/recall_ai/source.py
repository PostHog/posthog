from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.recallai import (
    RecallAISourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RecallAISource(SimpleSource[RecallAISourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RECALLAI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RECALL_AI,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Recall.ai",
            iconPath="/static/services/recall_ai.png",
            keywords=["meetings", "call recording", "transcripts", "bots"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
