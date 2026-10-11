from typing import cast

from sources.blackbaud_raisers_edge_nxt._config import BlackbaudRaisersEdgeNxtSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


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
