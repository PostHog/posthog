from typing import cast

from sources.microsoft_purview._config import MicrosoftPurviewSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MicrosoftPurviewSource(SimpleSource[MicrosoftPurviewSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTPURVIEW

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MICROSOFTPURVIEW,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Purview (Azure)",
            iconPath="/static/services/microsoft_purview.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
