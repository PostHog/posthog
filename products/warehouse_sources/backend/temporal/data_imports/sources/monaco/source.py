from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.monaco import MonacoSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MonacoSource(SimpleSource[MonacoSourceConfig]):
    api_docs_url = "https://docs.monaco.com/auth"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MONACO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MONACO,
            category=DataWarehouseSourceCategory.CRM,
            label="Monaco",
            keywords=["crm", "revenue", "pipeline"],
            iconPath="/static/services/monaco.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
