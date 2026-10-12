from typing import cast

from sources.clover._config import CloverSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class CloverSource(SimpleSource[CloverSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLOVER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CLOVER,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Clover (Fiserv)",
            iconPath="/static/services/clover.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
