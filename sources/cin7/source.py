from typing import cast

from sources.cin7._config import Cin7SourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class Cin7Source(SimpleSource[Cin7SourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CIN7

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CIN7,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Cin7",
            iconPath="/static/services/cin7.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
