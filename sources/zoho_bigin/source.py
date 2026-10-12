from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.zoho_bigin._config import ZohoBiginSourceConfig


@SourceRegistry.register
class ZohoBiginSource(SimpleSource[ZohoBiginSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZOHOBIGIN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ZOHOBIGIN,
            category=DataWarehouseSourceCategory.CRM,
            label="Zoho Bigin",
            iconPath="/static/services/zoho_bigin.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
