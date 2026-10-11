from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.two_c2p._config import TwoC2pSourceConfig


@SourceRegistry.register
class TwoC2pSource(SimpleSource[TwoC2pSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TWOC2P

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TWOC2P,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="2C2P (One Stop Payment Services)",
            iconPath="/static/services/two_c2p.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
