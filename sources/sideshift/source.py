from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.sideshift._config import SideShiftSourceConfig


@SourceRegistry.register
class SideShiftSource(SimpleSource[SideShiftSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SIDESHIFT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SIDESHIFT,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="SideShift",
            iconPath="/static/services/sideshift.png",
            keywords=["crypto", "exchange", "swaps"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
