from typing import cast

from sources.microsoft_defender_endpoint._config import MicrosoftDefenderEndpointSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MicrosoftDefenderEndpointSource(SimpleSource[MicrosoftDefenderEndpointSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTDEFENDERENDPOINT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MICROSOFTDEFENDERENDPOINT,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Defender for Endpoint",
            iconPath="/static/services/microsoft_defender_endpoint.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
