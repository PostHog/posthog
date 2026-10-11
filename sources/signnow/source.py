from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.signnow._config import SignNowSourceConfig


@SourceRegistry.register
class SignNowSource(SimpleSource[SignNowSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SIGNNOW

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SIGNNOW,
            category=DataWarehouseSourceCategory.SALES,
            label="SignNow",
            iconPath="/static/services/signnow.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
