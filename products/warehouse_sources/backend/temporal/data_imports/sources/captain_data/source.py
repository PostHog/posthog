from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.captaindata import (
    CaptainDataSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CaptainDataSource(SimpleSource[CaptainDataSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CAPTAINDATA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CAPTAINDATA,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Captain Data",
            iconPath="/static/services/captain_data.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
