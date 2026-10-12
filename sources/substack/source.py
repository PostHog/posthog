from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.substack._config import SubstackSourceConfig


@SourceRegistry.register
class SubstackSource(SimpleSource[SubstackSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SUBSTACK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SUBSTACK,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Substack",
            iconPath="/static/services/substack.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
