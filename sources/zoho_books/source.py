from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.zoho_books._config import ZohoBooksSourceConfig


@SourceRegistry.register
class ZohoBooksSource(SimpleSource[ZohoBooksSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZOHOBOOKS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ZOHOBOOKS,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Zoho Books",
            iconPath="/static/services/zoho_books.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
