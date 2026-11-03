from typing import cast

from products.warehouse_sources.sources.fathom._config import FathomSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class FathomSource(SimpleSource[FathomSourceConfig]):
    api_docs_url = "https://developers.fathom.ai"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FATHOM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FATHOM,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Fathom",
            iconPath="/static/services/fathom.png",
            keywords=["meeting notes", "note taker", "call recording"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
