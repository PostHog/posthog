from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RetellAISourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RetellAISource(SimpleSource[RetellAISourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RETELLAI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RETELL_AI,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Retell AI",
            iconPath="/static/services/retell_ai.png",
            keywords=["voice", "ai agent", "calls", "phone"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
