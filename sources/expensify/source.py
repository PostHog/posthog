from typing import cast

from sources.expensify._config import ExpensifySourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class ExpensifySource(SimpleSource[ExpensifySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EXPENSIFY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.EXPENSIFY,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Expensify",
            iconPath="/static/services/expensify.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
