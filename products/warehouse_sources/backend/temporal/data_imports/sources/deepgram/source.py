from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DeepgramSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DeepgramSource(SimpleSource[DeepgramSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DEEPGRAM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DEEPGRAM,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Deepgram",
            iconPath="/static/services/deepgram.png",
            keywords=["speech-to-text", "transcription", "voice ai", "usage"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
