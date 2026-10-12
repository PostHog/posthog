from typing import cast

from sources.openfec._config import OpenfecSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class OpenfecSource(SimpleSource[OpenfecSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OPENFEC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.OPENFEC,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="OpenFEC (US Federal Election Commission)",
            iconPath="/static/services/openfec.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
