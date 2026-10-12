from typing import cast

from sources.nolt._config import NoltSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class NoltSource(SimpleSource[NoltSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NOLT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NOLT,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Nolt",
            iconPath="/static/services/nolt.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
