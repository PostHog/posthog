from typing import cast

from sources.microsoft_lists._config import MicrosoftListsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MicrosoftListsSource(SimpleSource[MicrosoftListsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTLISTS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MICROSOFTLISTS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Microsoft Lists",
            iconPath="/static/services/microsoft_lists.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
