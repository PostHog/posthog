from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

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
