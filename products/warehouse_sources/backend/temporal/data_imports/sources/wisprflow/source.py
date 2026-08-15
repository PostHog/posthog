from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.wisprflow import (
    WisprFlowSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WisprFlowSource(SimpleSource[WisprFlowSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WISPRFLOW

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WISPR_FLOW,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Wispr Flow",
            iconPath="/static/services/wisprflow.png",
            keywords=["dictation", "voice", "speech to text", "transcription"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
