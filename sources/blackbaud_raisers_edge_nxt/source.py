from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.blackbaud_raisers_edge_nxt._config import BlackbaudRaisersEdgeNxtSourceConfig


@SourceRegistry.register
class BlackbaudRaisersEdgeNxtSource(SimpleSource[BlackbaudRaisersEdgeNxtSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BLACKBAUDRAISERSEDGENXT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BLACKBAUDRAISERSEDGENXT,
            category=DataWarehouseSourceCategory.CRM,
            label="Blackbaud Raiser's Edge NXT (SKY API)",
            iconPath="/static/services/blackbaud_raisers_edge_nxt.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
