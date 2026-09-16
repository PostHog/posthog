from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.quo import QuoSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class QuoSource(SimpleSource[QuoSourceConfig]):
    api_docs_url = "https://www.quo.com/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.QUO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.QUO,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Quo",
            keywords=["openphone", "phone", "sms"],
            iconPath="/static/services/quo.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
