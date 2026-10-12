from typing import cast

from sources.outlook._config import OutlookSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class OutlookSource(SimpleSource[OutlookSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OUTLOOK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.OUTLOOK,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Outlook",
            iconPath="/static/services/outlook.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
