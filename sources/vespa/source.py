from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.vespa._config import VespaSourceConfig


@SourceRegistry.register
class VespaSource(SimpleSource[VespaSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.VESPA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.VESPA,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Vespa",
            iconPath="/static/services/vespa.png",
            keywords=["vector database", "search", "ai", "documents"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
