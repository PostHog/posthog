from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.zoho_expense._config import ZohoExpenseSourceConfig


@SourceRegistry.register
class ZohoExpenseSource(SimpleSource[ZohoExpenseSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZOHOEXPENSE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ZOHOEXPENSE,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Zoho Expense",
            iconPath="/static/services/zoho_expense.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
