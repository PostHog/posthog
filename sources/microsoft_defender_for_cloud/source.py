from typing import cast

from sources.microsoft_defender_for_cloud._config import MicrosoftDefenderForCloudSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MicrosoftDefenderForCloudSource(SimpleSource[MicrosoftDefenderForCloudSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTDEFENDERFORCLOUD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MICROSOFTDEFENDERFORCLOUD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft (Defender for Cloud)",
            iconPath="/static/services/microsoft_defender_for_cloud.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
