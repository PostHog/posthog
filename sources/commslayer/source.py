from typing import cast

from sources.commslayer._config import CommslayerSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


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
