from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.opendatadc import (
    OpenDataDcSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OpenDataDcSource(SimpleSource[OpenDataDcSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OPENDATADC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.OPENDATADC,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Open Data DC",
            iconPath="/static/services/open_data_dc.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
