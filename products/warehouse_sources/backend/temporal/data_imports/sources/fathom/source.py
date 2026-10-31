from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fathom import FathomSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


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
