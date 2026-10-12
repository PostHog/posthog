from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.un_comtrade._config import UnComtradeSourceConfig


@SourceRegistry.register
class UnComtradeSource(SimpleSource[UnComtradeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.UNCOMTRADE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.UNCOMTRADE,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="UN Comtrade (United Nations Statistics Division)",
            iconPath="/static/services/un_comtrade.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
