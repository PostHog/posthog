from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.wistia import WistiaSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WistiaSource(SimpleSource[WistiaSourceConfig]):
    api_docs_url = "https://docs.wistia.com/reference/getting-started-with-the-data-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WISTIA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.WISTIA,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Wistia",
            iconPath="/static/services/wistia.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
