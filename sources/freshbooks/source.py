from typing import cast

from sources.freshbooks._config import FreshBooksSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class FreshBooksSource(SimpleSource[FreshBooksSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FRESHBOOKS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FRESHBOOKS,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="FreshBooks",
            iconPath="/static/services/freshbooks.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
