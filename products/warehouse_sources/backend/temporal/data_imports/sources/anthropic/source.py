from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AnthropicSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AnthropicSource(SimpleSource[AnthropicSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ANTHROPIC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ANTHROPIC,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Anthropic",
            iconPath="/static/services/anthropic.png",
            keywords=["llm", "claude", "ai usage", "cost"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
