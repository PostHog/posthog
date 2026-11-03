from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.conectocrm import (
    ConectoCRMSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ConectoCRMSource(SimpleSource[ConectoCRMSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CONECTOCRM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CONECTOCRM,
            category=DataWarehouseSourceCategory.CRM,
            label="Conecto CRM",
            iconPath="/static/services/conecto_crm.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
