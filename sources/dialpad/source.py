from typing import cast

from sources.dialpad._config import DialpadSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class DialpadSource(SimpleSource[DialpadSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DIALPAD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DIALPAD,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Dialpad",
            iconPath="/static/services/dialpad.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
