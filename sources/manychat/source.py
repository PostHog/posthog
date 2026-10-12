from typing import cast

from sources.manychat._config import ManychatSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class ManychatSource(SimpleSource[ManychatSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MANYCHAT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MANYCHAT,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Manychat",
            iconPath="/static/services/manychat.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
