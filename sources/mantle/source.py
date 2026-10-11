from typing import cast

from sources.mantle._config import MantleSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MantleSource(SimpleSource[MantleSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MANTLE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MANTLE,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Mantle",
            iconPath="/static/services/mantle.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
