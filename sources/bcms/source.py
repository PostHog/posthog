from typing import cast

from sources.bcms._config import BCMSSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class BCMSSource(SimpleSource[BCMSSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BCMS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BCMS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="BCMS",
            iconPath="/static/services/bcms.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
