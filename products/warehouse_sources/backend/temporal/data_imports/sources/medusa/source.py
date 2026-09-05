from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.medusa import MedusaSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MedusaSource(SimpleSource[MedusaSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MEDUSA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MEDUSA,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Medusa",
            iconPath="/static/services/medusa.png",
            keywords=["commerce", "ecommerce", "medusajs"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
