from typing import cast

from sources.microsoft_sentinel._config import MicrosoftSentinelSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MicrosoftSentinelSource(SimpleSource[MicrosoftSentinelSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTSENTINEL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MICROSOFTSENTINEL,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Sentinel (Azure Security Insights)",
            iconPath="/static/services/microsoft_sentinel.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
