from typing import cast

from sources.microsoft_dataverse._config import MicrosoftDataverseSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MicrosoftDataverseSource(SimpleSource[MicrosoftDataverseSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTDATAVERSE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MICROSOFTDATAVERSE,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Microsoft Dataverse",
            iconPath="/static/services/microsoft_dataverse.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
