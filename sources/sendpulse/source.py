from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.sendpulse._config import SendPulseSourceConfig


@SourceRegistry.register
class SendPulseSource(SimpleSource[SendPulseSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SENDPULSE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SENDPULSE,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="SendPulse",
            iconPath="/static/services/sendpulse.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
