from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.zoho_desk._config import ZohoDeskSourceConfig


@SourceRegistry.register
class ZohoDeskSource(SimpleSource[ZohoDeskSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZOHODESK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ZOHODESK,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Zoho Desk",
            iconPath="/static/services/zoho_desk.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
