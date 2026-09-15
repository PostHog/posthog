from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ringcentral import (
    RingCentralSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RingCentralSource(SimpleSource[RingCentralSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RINGCENTRAL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.RINGCENTRAL,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="RingCentral",
            iconPath="/static/services/ringcentral.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
