from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.blackbaudraisersedgenxt import (
    BlackbaudRaisersEdgeNxtSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BlackbaudRaisersEdgeNxtSource(SimpleSource[BlackbaudRaisersEdgeNxtSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BLACKBAUDRAISERSEDGENXT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BLACKBAUD_RAISERS_EDGE_NXT,
            category=DataWarehouseSourceCategory.CRM,
            label="Blackbaud Raiser's Edge NXT (SKY API)",
            iconPath="/static/services/blackbaud_raisers_edge_nxt.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
