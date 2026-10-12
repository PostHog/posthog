from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.neon_crm._config import NeonCrmSourceConfig


@SourceRegistry.register
class NeonCrmSource(SimpleSource[NeonCrmSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NEONCRM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NEONCRM,
            category=DataWarehouseSourceCategory.CRM,
            label="Neon One (Neon CRM)",
            iconPath="/static/services/neon_crm.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
