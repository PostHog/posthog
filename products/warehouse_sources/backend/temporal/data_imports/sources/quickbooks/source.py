from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import QuickBooksSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class QuickBooksSource(SimpleSource[QuickBooksSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.QUICKBOOKS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.QUICK_BOOKS,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            keywords=["qb"],
            label="QuickBooks",
            iconPath="/static/services/quickbooks.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
