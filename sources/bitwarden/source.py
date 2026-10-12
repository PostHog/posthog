from typing import cast

from sources.bitwarden._config import BitwardenSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class BitwardenSource(SimpleSource[BitwardenSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BITWARDEN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BITWARDEN,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Bitwarden, Inc.",
            iconPath="/static/services/bitwarden.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
