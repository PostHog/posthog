from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bolretailer import (
    BolRetailerSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BolRetailerSource(SimpleSource[BolRetailerSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BOLRETAILER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BOL_RETAILER,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="bol.com (bol Partner / Retailer API)",
            iconPath="/static/services/bol_retailer.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
