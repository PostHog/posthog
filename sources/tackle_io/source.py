from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.tackle_io._config import TackleIoSourceConfig


@SourceRegistry.register
class TackleIoSource(SimpleSource[TackleIoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TACKLEIO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TACKLEIO,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Tackle.io",
            iconPath="/static/services/tackle_io.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
