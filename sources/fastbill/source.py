from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.fastbill._config import FastbillSourceConfig


@SourceRegistry.register
class FastbillSource(SimpleSource[FastbillSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FASTBILL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FASTBILL,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Fastbill",
            iconPath="/static/services/fastbill.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
