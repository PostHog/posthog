from typing import cast

from sources.monaco._config import MonacoSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MonacoSource(SimpleSource[MonacoSourceConfig]):
    api_docs_url = "https://docs.monaco.com/auth"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MONACO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MONACO,
            category=DataWarehouseSourceCategory.CRM,
            label="Monaco",
            keywords=["crm", "revenue", "pipeline"],
            iconPath="/static/services/monaco.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
