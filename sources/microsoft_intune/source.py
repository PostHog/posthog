from typing import cast

from sources.microsoft_intune._config import MicrosoftIntuneSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MicrosoftIntuneSource(SimpleSource[MicrosoftIntuneSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTINTUNE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MICROSOFTINTUNE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Intune (Microsoft Graph)",
            iconPath="/static/services/microsoft_intune.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
