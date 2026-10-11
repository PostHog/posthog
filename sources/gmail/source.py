from typing import cast

from sources.gmail._config import GmailSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GmailSource(SimpleSource[GmailSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GMAIL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GMAIL,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Gmail",
            iconPath="/static/services/gmail.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
