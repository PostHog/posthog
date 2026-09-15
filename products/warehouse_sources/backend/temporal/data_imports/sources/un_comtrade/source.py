from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.uncomtrade import (
    UnComtradeSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


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
