from typing import cast

from sources.moesif._config import MoesifSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MoesifSource(SimpleSource[MoesifSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MOESIF

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MOESIF,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Moesif",
            iconPath="/static/services/moesif.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
