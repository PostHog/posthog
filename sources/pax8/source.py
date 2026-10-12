from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.pax8._config import Pax8SourceConfig


@SourceRegistry.register
class Pax8Source(SimpleSource[Pax8SourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PAX8

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PAX8,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Pax8",
            iconPath="/static/services/pax8.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
