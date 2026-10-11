from typing import cast

from sources.castor_edc._config import CastorEDCSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class CastorEDCSource(SimpleSource[CastorEDCSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CASTOREDC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CASTOREDC,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Castor EDC",
            iconPath="/static/services/castor_edc.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
