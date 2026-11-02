from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.commslayer import (
    CommslayerSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CommslayerSource(SimpleSource[CommslayerSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.COMMSLAYER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.COMMSLAYER,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Commslayer",
            iconPath="/static/services/commslayer.png",
            keywords=["helpdesk", "support", "shopify"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
