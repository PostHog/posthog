from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.msg91._config import MSG91SourceConfig


@SourceRegistry.register
class MSG91Source(SimpleSource[MSG91SourceConfig]):
    api_docs_url = "https://docs.msg91.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MSG91

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MSG91,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="MSG91",
            iconPath="/static/services/msg91.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
