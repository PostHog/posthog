from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lexwareoffice import (
    LexwareOfficeSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LexwareOfficeSource(SimpleSource[LexwareOfficeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LEXWAREOFFICE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LEXWAREOFFICE,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Lexware Office (formerly lexoffice), Haufe-Lexware GmbH",
            iconPath="/static/services/lexware_office.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
