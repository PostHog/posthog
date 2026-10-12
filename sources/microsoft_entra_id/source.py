from typing import cast

from sources.microsoft_entra_id._config import MicrosoftEntraIdSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MicrosoftEntraIdSource(SimpleSource[MicrosoftEntraIdSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTENTRAID

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MICROSOFTENTRAID,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Entra Id",
            iconPath="/static/services/microsoft_entra_id.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
