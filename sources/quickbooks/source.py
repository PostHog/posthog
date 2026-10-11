from typing import cast

from sources.quickbooks._config import QuickBooksSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class QuickBooksSource(SimpleSource[QuickBooksSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.QUICKBOOKS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.QUICKBOOKS,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            keywords=["qb"],
            label="QuickBooks",
            iconPath="/static/services/quickbooks.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
