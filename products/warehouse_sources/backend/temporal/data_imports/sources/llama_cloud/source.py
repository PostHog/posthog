from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LlamaCloudSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LlamaCloudSource(SimpleSource[LlamaCloudSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LLAMACLOUD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LLAMA_CLOUD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="LlamaCloud",
            iconPath="/static/services/llama_cloud.png",
            keywords=["llamaindex", "llamaparse", "document parsing", "rag"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
