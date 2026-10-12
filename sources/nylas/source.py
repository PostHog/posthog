from typing import cast

from sources.nylas._config import NylasSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class NylasSource(SimpleSource[NylasSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NYLAS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NYLAS,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Nylas",
            iconPath="/static/services/nylas.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
