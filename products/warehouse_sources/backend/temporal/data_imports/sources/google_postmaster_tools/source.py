from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googlepostmastertools import (
    GooglePostmasterToolsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GooglePostmasterToolsSource(SimpleSource[GooglePostmasterToolsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEPOSTMASTERTOOLS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOOGLEPOSTMASTERTOOLS,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Google Postmaster Tools",
            iconPath="/static/services/googlepostmastertools.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
