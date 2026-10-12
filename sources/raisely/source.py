from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.raisely._config import RaiselySourceConfig


@SourceRegistry.register
class RaiselySource(SimpleSource[RaiselySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RAISELY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.RAISELY,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Raisely",
            iconPath="/static/services/raisely.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
