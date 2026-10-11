from typing import cast

from sources.deputy._config import DeputySourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class DeputySource(SimpleSource[DeputySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DEPUTY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DEPUTY,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Deputy",
            iconPath="/static/services/deputy.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
