from typing import cast

from products.warehouse_sources.sources.leadlander._config import LeadLanderSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceKey,
    SourceRegistry,
    source_key,
)

SOURCE_KEY = "LeadLander"


@SourceRegistry.register
class LeadLanderSource(SimpleSource[LeadLanderSourceConfig]):
    api_docs_url = "https://leadlander.com/integrations/"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def credential_kind(self) -> str | None:
        return "leadlander"

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.CRM,
            label="LeadLander",
            iconPath="/static/warehouse-sources/leadlander/icon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
