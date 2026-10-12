from typing import cast

from sources.arxiv._config import ArxivSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class ArxivSource(SimpleSource[ArxivSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ARXIV

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ARXIV,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="arXiv (Cornell University)",
            iconPath="/static/services/arxiv.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
