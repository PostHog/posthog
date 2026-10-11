from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.nobl9._config import Nobl9SourceConfig


@SourceRegistry.register
class Nobl9Source(SimpleSource[Nobl9SourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NOBL9

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NOBL9,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Nobl9",
            iconPath="/static/services/nobl9.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
