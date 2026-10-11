from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.wisprflow._config import WisprFlowSourceConfig


@SourceRegistry.register
class WisprFlowSource(SimpleSource[WisprFlowSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WISPRFLOW

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.WISPRFLOW,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Wispr Flow",
            iconPath="/static/services/wisprflow.png",
            keywords=["dictation", "voice", "speech to text", "transcription"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
