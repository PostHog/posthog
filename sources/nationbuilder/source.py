from typing import cast

from sources.nationbuilder._config import NationBuilderSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class NationBuilderSource(SimpleSource[NationBuilderSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NATIONBUILDER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NATIONBUILDER,
            category=DataWarehouseSourceCategory.CRM,
            label="NationBuilder",
            iconPath="/static/services/nationbuilder.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
